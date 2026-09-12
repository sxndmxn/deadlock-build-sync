use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{RankRange, Result, integer, sha256};
use deadlock_guides::{SUPPORT, calculate_rank_cutoffs};
use serde_json::{Value, json};

use crate::branch_candidates::{freeze_candidates, freeze_substitutions};
use crate::checkpoint_data::load_checkpoints;
use crate::core_outcomes::evaluate_core;
use crate::database::AnalysisDatabase;
use crate::discovery_data::{DiscoveryData, load_discovery_data};
use crate::discovery_models::{ExportContext, FrozenHero, Nomination, item_ids};
use crate::grouping::{group_candidates, group_item_candidates};
use crate::mechanic_overlap::describe_overlap;
use crate::mining::{Candidate, mine_candidates};
use crate::purchase_orders::select_order;
use crate::purchase_pool::freeze_guide;

pub fn core_identity(hero: u64, items: &[u64]) -> String {
    let mut items = items.to_vec();
    items.sort_unstable();
    let content = format!(
        "[{}]",
        items
            .iter()
            .map(u64::to_string)
            .collect::<Vec<_>>()
            .join(", ")
    );
    format!("{hero}-{}", &sha256(content.as_bytes())[..16])
}

pub fn freeze_hero(hero: &Value, context: &ExportContext) -> Result<FrozenHero> {
    let identifier = integer(hero, "id")?;
    eprintln!("Discovering {}", hero["name"].as_str().unwrap_or("hero"));
    let database = context.open_database(identifier)?;
    let cutoffs = calculate_rank_cutoffs(
        context.ranks.minimum,
        context.ranks.maximum,
        context.expansion,
    )?;
    let mut history = Vec::new();
    let mut final_result = None;
    for minimum in cutoffs {
        let ranks = RankRange {
            minimum,
            maximum: context.ranks.maximum,
        };
        let data = load_discovery_data(&database, identifier, &context.graph, ranks)?;
        let mining = mine_candidates(&data, &context.graph)?;
        deadlock_data::atomic_write_json(
            &context.paths.tables.join(format!(
                "hero-{identifier}-rank-{}-mining.json",
                minimum.badge()
            )),
            &json!({"sizes":mining.sizes,"candidates":mining.candidates}),
        )?;
        let mut candidates = mining
            .candidates
            .iter()
            .filter(|candidate| candidate.items.len() >= 4)
            .cloned()
            .collect::<Vec<_>>();
        let (mut rows, mut grouping) =
            select_nominations(&database, hero, &data, &mut candidates, context)?;
        if rows.is_empty() {
            let mut seeds = mining
                .candidates
                .into_iter()
                .filter(|candidate| candidate.items.len() == 3)
                .collect::<Vec<_>>();
            (rows, grouping) = select_nominations(&database, hero, &data, &mut seeds, context)?;
            candidates.extend(seeds);
        }
        history.push(json!({"minimum_badge":minimum.badge(),"maximum_badge":ranks.maximum.badge(),"discovery_rows":data.fold_rows("discovery").count(),
            "selection_rows":data.fold_rows("selection").count(),"candidate_count":candidates.len(),"discovery_owners":candidates.iter().map(|candidate|candidate.discovery_support).max().unwrap_or(0),
            "selection_owners":candidates.iter().filter_map(|candidate|candidate.selection["owners"].as_u64()).max().unwrap_or(0),"supported_builds":rows.len(),
            "reason":if rows.is_empty(){"no supported legal path"}else{"supported build available"}}));
        let supported = !rows.is_empty();
        if supported {
            let decisions = load_checkpoints(
                &database,
                identifier,
                &context.graph,
                minimum.badge(),
                ranks.maximum.badge(),
            )?;
            for row in &mut rows {
                row.branch_candidates = freeze_candidates(&decisions, row, &context.graph)?;
            }
            freeze_substitutions(&decisions, &mut rows, &context.graph)?;
        }
        final_result = Some(FrozenHero {
            cohort: json!({"minimum_badge":minimum.badge(),"maximum_badge":ranks.maximum.badge(),"rank_expansion":context.expansion,"expansion_history":history}),
            rows,
            candidate_count: candidates.len(),
            grouping,
            candidates,
        });
        if supported {
            break;
        }
    }
    final_result.ok_or_else(|| deadlock_data::Error::new("Discovery has no rank cutoff"))
}

fn select_nominations(
    database: &AnalysisDatabase,
    hero: &Value,
    data: &DiscoveryData,
    candidates: &mut [Candidate],
    context: &ExportContext,
) -> Result<(Vec<Nomination>, Value)> {
    candidates.sort_by(|left, right| left.items.cmp(&right.items));
    let grouping = group_candidates(candidates, data)?;
    let groups: Vec<Vec<usize>> = serde_json::from_value(grouping["groups"].clone())?;
    let memberships = groups
        .iter()
        .enumerate()
        .flat_map(|(group, indices)| indices.iter().map(move |index| (*index, group)))
        .collect::<BTreeMap<_, _>>();
    for candidate in &mut *candidates {
        candidate.identity_id = core_identity(data.hero, &candidate.items);
        candidate.selection = evaluate_core(data, &candidate.items, "selection")?;
        candidate.selection_rejections = SUPPORT.core_reasons(
            candidate.discovery_support,
            integer(&candidate.selection, "owners")?,
        );
    }
    let mut ranked = (0..candidates.len())
        .filter(|index| candidates[*index].selection_rejections.is_empty())
        .collect::<Vec<_>>();
    ranked.sort_by(|left, right| {
        let first = &candidates[*left];
        let second = &candidates[*right];
        let lower = |candidate: &Candidate| {
            candidate.selection["adjusted"]["lower_95"]
                .as_f64()
                .unwrap_or(f64::NEG_INFINITY)
        };
        lower(second)
            .total_cmp(&lower(first))
            .then_with(|| {
                second.selection["owners"]
                    .as_u64()
                    .cmp(&first.selection["owners"].as_u64())
            })
            .then_with(|| first.items.cmp(&second.items))
    });
    let mut used = BTreeSet::new();
    let mut rows = Vec::new();
    for (rank, index) in ranked.into_iter().enumerate() {
        if used.contains(&memberships[&index]) {
            continue;
        }
        match nominate(database, hero, data, &candidates[index], rank, context) {
            Ok(nomination) => {
                used.insert(memberships[&index]);
                rows.push(nomination);
            }
            Err(error) => candidates[index]
                .selection_rejections
                .push(error.to_string()),
        }
    }
    Ok((rows, grouping))
}

fn nominate(
    database: &AnalysisDatabase,
    hero: &Value,
    data: &DiscoveryData,
    candidate: &Candidate,
    rank: usize,
    context: &ExportContext,
) -> Result<Nomination> {
    let path = select_order(data, &candidate.items, &context.graph)?;
    if path["admitted_before_validation"] != true {
        return Err(deadlock_data::Error::new(
            path["reason"].as_str().unwrap_or("No supported legal path"),
        ));
    }
    let guide = freeze_guide(
        database,
        data,
        &candidate.items,
        &item_ids(&path["order"])?,
        &context.graph,
        None,
    )?;
    Ok(Nomination {
        candidate: candidate.clone(),
        hero_id: data.hero,
        selection_rank: rank,
        path,
        guide,
        tactics: describe_overlap(hero, &candidate.items, &context.normal_assets)?,
        branch_candidates: Vec::new(),
    })
}

pub fn assign_group_ids(nominations: &[Nomination]) -> Result<BTreeMap<String, String>> {
    let mut rows = nominations.iter().collect::<Vec<_>>();
    rows.sort_by(|left, right| left.candidate.items.cmp(&right.candidate.items));
    let candidates = rows
        .iter()
        .map(|row| row.candidate.clone())
        .collect::<Vec<_>>();
    let grouping = group_item_candidates(&candidates)?;
    let groups: Vec<Vec<usize>> = serde_json::from_value(grouping["groups"].clone())?;
    let mut result = BTreeMap::new();
    for group in groups {
        let default = *group
            .iter()
            .min_by_key(|index| rows[**index].selection_rank)
            .ok_or_else(|| deadlock_data::Error::new("Guide group is empty"))?;
        for index in group {
            result.insert(
                rows[index].candidate.identity_id.clone(),
                rows[default].candidate.identity_id.clone(),
            );
        }
    }
    Ok(result)
}
