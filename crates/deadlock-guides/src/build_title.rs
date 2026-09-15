use std::collections::BTreeSet;

use chrono::DateTime;
use deadlock_data::{Error, Result};

use crate::guide_item::GuideItem;
use crate::purchase_guide::PurchaseGuide;

pub const MAX_BUILD_NAME_CHARACTERS: usize = 50;

pub fn format_date(timestamp: u64, compact: bool) -> Result<String> {
    if timestamp == 0 {
        return Ok(if compact { "????" } else { "UNRESOLVED" }.into());
    }
    let time = DateTime::from_timestamp(i64::try_from(timestamp)?, 0)
        .ok_or_else(|| Error::new("Build timestamp is outside the supported date range"))?;
    Ok(time
        .format(if compact { "%m%d" } else { "%Y-%m-%d" })
        .to_string())
}

/// # Errors
/// Returns an error when the persona or core item name is empty, or the core item name exceeds the title limit.
pub fn format_build_name(
    persona: &str,
    build_name: &str,
    _patch_title: &str,
    _statistics_window: &str,
) -> Result<String> {
    let persona = persona.split_whitespace().collect::<Vec<_>>().join(" ");
    if persona.is_empty() {
        return Err(Error::new("Persona must contain visible text"));
    }
    let build = build_name.trim();
    if build.is_empty() || build.chars().count() > MAX_BUILD_NAME_CHARACTERS {
        return Err(Error::new(
            "Core item name is empty or exceeds the title limit",
        ));
    }
    let named = format!("{persona} | {build}");
    Ok(if named.chars().count() <= MAX_BUILD_NAME_CHARACTERS {
        named
    } else {
        build.into()
    })
}

pub fn select_core_item_name(core: &[GuideItem]) -> Result<String> {
    select_available_core_name(core, &[], &BTreeSet::new())
}

pub fn assign_core_item_names(guides: &mut [PurchaseGuide]) -> Result<()> {
    let mut used = BTreeSet::new();
    let mut names = Vec::new();
    for guide in guides.iter() {
        let peers = guides
            .iter()
            .filter(|peer| peer.hero_id == guide.hero_id)
            .map(|peer| peer.core_items.as_slice())
            .collect::<Vec<_>>();
        let existing = used
            .iter()
            .filter(|(hero, _)| *hero == guide.hero_id)
            .map(|(_, name): &(u64, String)| name.clone())
            .collect();
        let name = select_available_core_name(&guide.core_items, &peers, &existing)?;
        used.insert((guide.hero_id, name.clone()));
        names.push(name);
    }
    for (guide, name) in guides.iter_mut().zip(names) {
        guide.build_archetype = name;
    }
    Ok(())
}

fn select_available_core_name(
    core: &[GuideItem],
    peers: &[&[GuideItem]],
    used: &BTreeSet<String>,
) -> Result<String> {
    let mut ordered = core.iter().collect::<Vec<_>>();
    ordered.sort_by_key(|item| std::cmp::Reverse(item.tier));
    let first = ordered
        .first()
        .ok_or_else(|| Error::new("Build name requires core items"))?;
    let mut candidates = Vec::new();
    for (first_order, first) in ordered.iter().enumerate() {
        for (second_order, second) in ordered.iter().enumerate().skip(first_order + 1) {
            let count = peers
                .iter()
                .filter(|peer| {
                    peer.iter().any(|item| item.item_id == first.item_id)
                        && peer.iter().any(|item| item.item_id == second.item_id)
                })
                .count();
            candidates.push((
                first_order,
                count,
                second_order,
                format!("{} / {}", first.name, second.name),
            ));
        }
    }
    if ordered.len() == 1 {
        candidates.push((0, 0, 0, first.name.clone()));
    }
    candidates.sort();
    candidates
        .into_iter()
        .map(|(_, _, _, name)| name)
        .find(|name| name.chars().count() <= MAX_BUILD_NAME_CHARACTERS && !used.contains(name))
        .ok_or_else(|| Error::new("Core items cannot form a distinct name within the title limit"))
}
