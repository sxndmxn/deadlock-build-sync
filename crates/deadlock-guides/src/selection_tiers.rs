use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};
use deadlock_input::ItemGraph;

use crate::hero_evidence::HeroBuildEvidence;
use crate::item_evidence::ItemEvidence;
use crate::selection_paths::ItemEvidenceIndex;

pub fn select_tiers(
    graph: &ItemGraph,
    evidence: &HeroBuildEvidence,
    items: &ItemEvidenceIndex<'_>,
) -> Result<BTreeMap<u8, Vec<ItemEvidence>>> {
    let core = evidence
        .sequence_policy
        .content()
        .default_path
        .iter()
        .copied()
        .collect::<BTreeSet<_>>();
    let situations = evidence
        .situational_policy
        .branches()
        .iter()
        .map(|branch| branch.content().item_id)
        .collect::<BTreeSet<_>>();
    if !situations.is_disjoint(&core) {
        return Err(Error::new("Situational items repeat the selected core"));
    }
    let mut unavailable = core;
    unavailable.extend(
        evidence
            .core_policy
            .content()
            .alternatives
            .iter()
            .map(|row| row.content().item_id),
    );
    let mut visible = unavailable.clone();
    let mut result = BTreeMap::new();
    for (tier, ids) in evidence.tier_policy.item_ids_by_tier().iter().rev() {
        let membership = select_tier_membership(
            graph,
            items,
            ids,
            &unavailable,
            &visible,
            evidence.tier_policy.discovery_pool(),
        )?;
        visible.extend(ids);
        result.insert(*tier, membership);
    }
    let selected = result
        .values()
        .flatten()
        .map(|item| item.content().item_id)
        .collect();
    if !situations.is_subset(&selected) {
        return Err(Error::new(
            "Situational items are absent from the tier policy",
        ));
    }
    Ok(result)
}

fn select_tier_membership(
    graph: &ItemGraph,
    items: &ItemEvidenceIndex<'_>,
    ids: &[u64],
    unavailable: &BTreeSet<u64>,
    visible: &BTreeSet<u64>,
    discovery: bool,
) -> Result<Vec<ItemEvidence>> {
    let mut membership = Vec::new();
    for id in ids {
        let item = items
            .get(id)
            .ok_or_else(|| Error::new("Tier item has no evidence"))?;
        let upgrades = graph.children(*id)?;
        if unavailable.contains(id)
            || (!discovery
                && !upgrades.is_empty()
                && upgrades.iter().all(|id| !visible.contains(id)))
        {
            return Err(Error::new(
                "Tier policy has an unavailable item or hidden upgrade",
            ));
        }
        membership.push((*item).clone());
    }
    if !discovery
        && !membership.is_sorted_by(|left, right| compare_purchase_windows(left, right).is_le())
    {
        return Err(Error::new("Tier policy order is not deterministic"));
    }
    Ok(membership)
}

fn compare_purchase_windows(left: &ItemEvidence, right: &ItemEvidence) -> Ordering {
    let priority = |item: &ItemEvidence| {
        let reliable = item.reliable_purchase_window().is_some();
        let item = item.content();
        (
            !reliable,
            if reliable {
                item.selection_median_valid_buy_net_worth
                    .unwrap_or(f64::INFINITY)
            } else {
                f64::INFINITY
            },
            if reliable {
                item.selection_median_buy_time_s.unwrap_or(f64::INFINITY)
            } else {
                f64::INFINITY
            },
            item.item_id,
        )
    };
    let left = priority(left);
    let right = priority(right);
    left.0
        .cmp(&right.0)
        .then_with(|| left.1.total_cmp(&right.1))
        .then_with(|| left.2.total_cmp(&right.2))
        .then(left.3.cmp(&right.3))
}
