use std::collections::BTreeMap;

use deadlock_data::{Result, array, count_ratio, integer};
use deadlock_guides::{
    PurchaseState, find_first_incomplete_checkpoint, is_item_or_upgrade_owned, plan_purchases,
};
use deadlock_input::ItemGraph;
use serde_json::{Value, json};

use crate::discovery_models::{Nomination, item_ids};

pub fn conditions(row: &Value) -> Vec<(String, Value)> {
    let mut result = Vec::new();
    if let Some(relative) = row["relative_wealth"].as_f64() {
        result.push((
            "relative_wealth".into(),
            if relative < 0.9 {
                "behind"
            } else if relative > 1.1 {
                "ahead"
            } else {
                "even"
            }
            .into(),
        ));
    }
    for (field, condition) in [
        ("enemy_heroes", "enemy_hero"),
        ("enemy_items", "enemy_item"),
    ] {
        let mut identifiers = row[field]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(Value::as_u64)
            .collect::<Vec<_>>();
        identifiers.sort_unstable();
        identifiers.dedup();
        for value in identifiers {
            result.push((condition.into(), value.into()));
        }
    }
    result
}

pub fn legal_choice(
    row: &Value,
    nominee: &Nomination,
    item: u64,
    checkpoint: usize,
    graph: &ItemGraph,
) -> Result<bool> {
    let owned = item_ids(&row["owned_before"])?;
    if find_first_incomplete_checkpoint(graph, &nominee.guide.path, &owned)? != checkpoint
        || is_item_or_upgrade_owned(graph, item, &owned)?
    {
        return Ok(false);
    }
    let state = PurchaseState {
        owned,
        ..PurchaseState::default()
    };
    Ok(plan_purchases(
        graph,
        &nominee.guide.path,
        &nominee.candidate.items,
        &BTreeMap::from([(item, checkpoint)]),
        &state,
    )
    .is_ok()
        && plan_purchases(
            graph,
            &nominee.guide.path,
            &nominee.candidate.items,
            &BTreeMap::new(),
            &state,
        )
        .is_ok())
}

pub fn select_choice_rows(
    rows: &[Value],
    nominee: &Nomination,
    item: u64,
    checkpoint: usize,
    comparator: u64,
    graph: &ItemGraph,
) -> Result<Vec<Value>> {
    Ok(
        select_choice_indices(rows, nominee, item, checkpoint, comparator, graph)?
            .into_iter()
            .map(|index| rows[index].clone())
            .collect(),
    )
}

pub fn select_choice_indices(
    rows: &[Value],
    nominee: &Nomination,
    item: u64,
    checkpoint: usize,
    comparator: u64,
    graph: &ItemGraph,
) -> Result<Vec<usize>> {
    let mut legal = BTreeMap::new();
    let mut selected = Vec::new();
    for (index, row) in rows
        .iter()
        .enumerate()
        .filter(|(_, row)| row["item_id"] == item || row["item_id"] == comparator)
        .filter(|(_, row)| !row["relative_wealth"].is_null())
    {
        let owned = item_ids(&row["owned_before"])?;
        let valid = if let Some(valid) = legal.get(&owned) {
            *valid
        } else {
            let valid = legal_choice(row, nominee, item, checkpoint, graph)?;
            legal.insert(owned, valid);
            valid
        };
        if valid {
            selected.push(index);
        }
    }
    Ok(selected)
}

pub fn freeze_candidates(
    rows: &[Value],
    nominee: &Nomination,
    graph: &ItemGraph,
) -> Result<Vec<Value>> {
    let mut candidates = Vec::new();
    for record in array(&nominee.guide.purchase_timing["items"])? {
        let counts = item_ids(&record["counts_by_checkpoint"])?;
        let Some((checkpoint, count)) = counts
            .iter()
            .enumerate()
            .max_by(|left, right| left.1.cmp(right.1).then_with(|| right.0.cmp(&left.0)))
        else {
            continue;
        };
        if *count < 20
            || count_ratio(*count, integer(record, "buyers")?.max(1))? < 0.1
            || checkpoint >= nominee.guide.path.len()
        {
            continue;
        }
        candidates.extend(freeze_conditions(
            rows,
            nominee,
            integer(record, "item_id")?,
            checkpoint,
            graph,
        )?);
    }
    Ok(candidates)
}

pub fn freeze_conditions(
    rows: &[Value],
    nominee: &Nomination,
    item: u64,
    checkpoint: usize,
    graph: &ItemGraph,
) -> Result<Vec<Value>> {
    if plan_purchases(
        graph,
        &nominee.guide.path,
        &nominee.candidate.items,
        &BTreeMap::from([(item, checkpoint)]),
        &PurchaseState::default(),
    )
    .is_err()
    {
        return Ok(Vec::new());
    }
    let comparator = nominee.guide.path[checkpoint];
    let selected = select_choice_rows(rows, nominee, item, checkpoint, comparator, graph)?;
    let mut counts = BTreeMap::<(String, String, u64), u64>::new();
    let mut triggers = BTreeMap::new();
    for row in selected.iter().filter(|row| row["fold"] == "train") {
        for (condition, trigger) in conditions(row) {
            let key = (condition, serde_json::to_string(&trigger)?);
            *counts
                .entry((key.0.clone(), key.1.clone(), integer(row, "item_id")?))
                .or_default() += 1;
            triggers.insert(key, trigger);
        }
    }
    Ok(triggers.into_iter().filter(|((condition,key),_)|[item,comparator].iter().all(|action|counts.get(&(condition.clone(),key.clone(),*action)).copied().unwrap_or(0)>=20))
        .map(|((condition,_),trigger)|json!({"item_id":item,"after_step":checkpoint,"comparator_item_id":comparator,"condition":condition,"value":trigger})).collect())
}

pub fn freeze_substitutions(
    rows: &[Value],
    nominees: &mut [Nomination],
    graph: &ItemGraph,
) -> Result<()> {
    let originals = nominees.to_vec();
    for base in nominees {
        for alternative in &originals {
            let Some(checkpoint) = substitution_checkpoint(base, alternative) else {
                continue;
            };
            let item = alternative.guide.path[checkpoint];
            for mut candidate in freeze_conditions(rows, base, item, checkpoint, graph)? {
                candidate["substitution"] = json!({"source_identity_id":alternative.candidate.identity_id,"core":alternative.path["order"],"path":alternative.guide.path});
                base.branch_candidates.push(candidate);
            }
        }
    }
    Ok(())
}

fn substitution_checkpoint(base: &Nomination, alternative: &Nomination) -> Option<usize> {
    if base.candidate.identity_id == alternative.candidate.identity_id
        || base.guide.path.len() != alternative.guide.path.len()
    {
        return None;
    }
    let changed = base
        .guide
        .path
        .iter()
        .zip(&alternative.guide.path)
        .enumerate()
        .filter(|(_, pair)| pair.0 != pair.1)
        .map(|(index, _)| index)
        .collect::<Vec<_>>();
    if changed.len() != 1
        || base
            .candidate
            .items
            .iter()
            .filter(|item| !alternative.candidate.items.contains(item))
            .count()
            != 1
    {
        return None;
    }
    let checkpoint = changed[0];
    let item = alternative.guide.path[checkpoint];
    (base
        .guide
        .pool
        .values()
        .flatten()
        .any(|value| *value == item)
        && alternative.candidate.items.contains(&item)
        && base.candidate.items.contains(&base.guide.path[checkpoint]))
    .then_some(checkpoint)
}
