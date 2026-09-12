use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::Result;
use deadlock_input::ItemGraph;

use crate::purchase_guidance_types::{PurchaseChoice, PurchaseDecision};

/// # Errors
/// Returns an error when an upgrade references an unknown component.
pub fn build_checkpoint_decisions(
    position: usize,
    choices: &[PurchaseChoice],
    graph: &ItemGraph,
) -> Result<Vec<PurchaseDecision>> {
    let cards = choices
        .iter()
        .filter(|card| card.after_step == Some(position) && card.plan.is_some())
        .collect::<Vec<_>>();
    let ancestors = cards
        .iter()
        .flat_map(|card| components(card))
        .copied()
        .collect::<BTreeSet<_>>();
    let options = cards
        .into_iter()
        .filter(|card| !ancestors.contains(&card.item_id))
        .collect();
    let mut grouped = BTreeMap::<String, Vec<&PurchaseChoice>>::new();
    let mut result = Vec::new();
    for group in group_shared_components(options) {
        let Some(first) = group.first() else {
            continue;
        };
        if group.len() > 1 {
            let mut common = components(first).iter().copied().collect::<BTreeSet<_>>();
            for card in &group[1..] {
                common.retain(|item| components(card).contains(item));
            }
            let label = if common.is_empty() {
                "Shared component upgrades".into()
            } else {
                let names = common
                    .iter()
                    .map(|id| Ok(graph.require(*id)?.name.as_str()))
                    .collect::<Result<Vec<_>>>()?;
                format!("Upgrade {}", names.join(", "))
            };
            result.push(build_decision(position, label, group, true));
        } else {
            let label = if first.purpose.basis == "unclassified" {
                &first.name
            } else {
                &first.purpose.label
            };
            grouped.entry(label.clone()).or_default().push(first);
        }
    }
    result.extend(
        grouped
            .into_iter()
            .map(|(label, rows)| build_decision(position, label, rows, false)),
    );
    result.sort_by(|left, right| {
        left.purpose
            .cmp(&right.purpose)
            .then_with(|| left.options.cmp(&right.options))
    });
    Ok(result)
}

fn components(card: &PurchaseChoice) -> &[u64] {
    card.route
        .split_last()
        .map_or(&[], |(_, components)| components)
}

fn group_shared_components(mut remaining: Vec<&PurchaseChoice>) -> Vec<Vec<&PurchaseChoice>> {
    let mut groups = Vec::new();
    while !remaining.is_empty() {
        let seed = remaining.remove(0);
        let mut group = vec![seed];
        let mut parts = components(seed).iter().copied().collect::<BTreeSet<_>>();
        loop {
            let (joined, rest): (Vec<_>, Vec<_>) = remaining
                .into_iter()
                .partition(|card| components(card).iter().any(|id| parts.contains(id)));
            remaining = rest;
            if joined.is_empty() {
                break;
            }
            parts.extend(joined.iter().flat_map(|card| components(card)).copied());
            group.extend(joined);
        }
        groups.push(group);
    }
    groups
}

fn build_decision(
    position: usize,
    purpose: String,
    mut rows: Vec<&PurchaseChoice>,
    upgrade_fork: bool,
) -> PurchaseDecision {
    rows.sort_by_key(|card| {
        (
            std::cmp::Reverse(card.timing.as_ref().map_or(0, |timing| timing.buyers)),
            card.item_id,
        )
    });
    let kind = if rows.len() > 1 {
        "PICK ONE"
    } else if rows.first().is_some_and(|row| row.route.len() > 1) {
        "UPGRADE"
    } else {
        "OPTIONAL"
    };
    PurchaseDecision {
        after_step: position,
        kind: kind.into(),
        purpose,
        options: rows.iter().map(|row| row.item_id).collect(),
        upgrade_fork,
    }
}
