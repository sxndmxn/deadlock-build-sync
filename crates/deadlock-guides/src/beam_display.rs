use std::fmt::Write as _;

use deadlock_data::{Result, count_as_f64};
use serde_json::Value;

use crate::purchase_guide::PurchaseGuide;

#[must_use]
pub fn generator_metadata(guide: &PurchaseGuide) -> Option<&Value> {
    guide
        .evidence_summary
        .get("generator")
        .filter(|value| value.is_object())
}

#[must_use]
pub fn variant_state_labels(guide: &PurchaseGuide) -> String {
    let rows = variant_state_rows(guide);
    if rows.is_empty() {
        "State unknown".into()
    } else {
        rows.iter()
            .map(|(label, _)| *label)
            .collect::<Vec<_>>()
            .join(", ")
    }
}

fn variant_state_rows(guide: &PurchaseGuide) -> Vec<(&'static str, &Value)> {
    let Some(metadata) = generator_metadata(guide) else {
        return Vec::new();
    };
    let mut rows = Vec::new();
    for (state, label) in [(0, "Behind"), (1, "Even"), (2, "Ahead")] {
        if !metadata["states"]
            .as_array()
            .is_some_and(|states| states.contains(&Value::from(state)))
        {
            continue;
        }
        let row = &metadata["state_evidence"][state.to_string()]["validation"];
        if row["owners"]
            .as_u64()
            .zip(row["wins"].as_u64())
            .is_some_and(|(owners, wins)| owners > 0 && wins <= owners)
        {
            rows.push((label, row));
        }
    }
    rows
}

/// # Errors
/// Returns an error when observation counts exceed the supported numeric range.
pub fn variant_statistics(guide: &PurchaseGuide, detailed: bool) -> Result<Vec<String>> {
    let mut lines = Vec::new();
    for (label, row) in variant_state_rows(guide) {
        let count = deadlock_data::integer(row, "owners")?;
        let wins = deadlock_data::integer(row, "wins")?;
        let rate = 100.0 * count_as_f64(wins)? / count_as_f64(count)?;
        let mut text = format!("{label}: {rate:.1}% | {wins}/{count} wins");
        if detailed {
            write!(
                text,
                " | 95% interval {:.1}%–{:.1}%. State hero baseline: {:.1}% across {} matches.",
                deadlock_data::real(row, "lower_95")? * 100.0,
                deadlock_data::real(row, "upper_95")? * 100.0,
                deadlock_data::real(row, "hero_win_rate")? * 100.0,
                deadlock_data::integer(row, "hero_matches")?
            )?;
            if let Some(cutoff) = row["ownership_before_seconds"]
                .as_u64()
                .filter(|value| *value > 0)
            {
                write!(
                    text,
                    " All final core items owned before {cutoff} seconds; additional items allowed."
                )?;
            }
        }
        lines.push(text);
    }
    Ok(lines)
}

pub fn attach_beam_ability_names(guide: &mut PurchaseGuide, kit: &Value) {
    if generator_metadata(guide).is_none() {
        return;
    }
    let names = kit["abilities"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|row| {
            row["id"]
                .as_u64()
                .zip(row["name"].as_str())
                .map(|(id, name)| (id.to_string(), name.into()))
        })
        .collect();
    guide.evidence_summary["ability_names"] = Value::Object(names);
}
