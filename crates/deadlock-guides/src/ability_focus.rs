use deadlock_data::{Error, Result};
use serde_json::Value;

use crate::build_tags::first_fully_upgraded_ability;
use crate::build_title::format_build_title;
use crate::hero_build::{AbilityFocus, BuildItem, HeroBuild};

/// Assigns an inferred ability focus, its icon, and a title without the hero name.
///
/// # Errors
/// Returns an error when the key item is absent from CORE.
pub fn assign_build_focus(build: &mut HeroBuild, assets: &[Value]) -> Result<()> {
    let upgrade_ability = first_fully_upgraded_ability(&build.ability_ids).ok();
    if let Some(ability) = upgrade_ability {
        build.tag_ids[0] = ability;
    }
    let focus = select_ability_focus(build, assets);
    let key_item = build
        .key_item()
        .ok_or_else(|| Error::new("Build key item is not in CORE"))?;
    build.title = format_build_title(
        focus.as_ref().map(|focus| focus.name.as_str()).or_else(|| {
            build
                .key_ability_name
                .as_deref()
                .filter(|name| upgrade_ability.is_some() && !name.trim().is_empty())
        }),
        &key_item.name,
    );
    if let Some(focus) = &focus {
        build.tag_ids[0] = focus.ability_id;
    }
    build.ability_focus = focus;
    Ok(())
}

fn select_ability_focus(build: &HeroBuild, assets: &[Value]) -> Option<AbilityFocus> {
    let supporters = build
        .core
        .iter()
        .filter_map(|item| select_focus_target(item, assets).map(|ability| (item.item_id, ability)))
        .collect::<Vec<_>>();
    let ability_id = supporters.first()?.1;
    if supporters.iter().any(|(_, ability)| *ability != ability_id) {
        return None;
    }
    let supports_key_item = supporters
        .iter()
        .any(|(item, _)| *item == build.key_item_id);
    let supports_ability_order =
        first_fully_upgraded_ability(&build.ability_ids).ok() == Some(ability_id);
    if !supports_key_item && supporters.len() < 2 && !supports_ability_order {
        return None;
    }
    let ability = assets
        .iter()
        .find(|asset| asset["id"].as_u64() == Some(ability_id))?;
    let belongs_to_hero = ability["hero"].as_u64() == Some(build.hero_id)
        || ability["heroes"].as_array().is_some_and(|heroes| {
            heroes
                .iter()
                .any(|hero| hero.as_u64() == Some(build.hero_id))
        });
    let name = ability["name"].as_str()?.trim();
    if ability["type"] != "ability"
        || !belongs_to_hero
        || name.is_empty()
        || !build.ability_ids.contains(&ability_id)
    {
        return None;
    }
    Some(AbilityFocus {
        ability_id,
        name: name.into(),
        supporting_item_ids: supporters.into_iter().map(|(item, _)| item).collect(),
    })
}

fn select_focus_target(item: &BuildItem, assets: &[Value]) -> Option<u64> {
    let target = item.imbue_target.as_ref()?;
    target.validate().ok()?;
    let asset = assets
        .iter()
        .find(|asset| asset["id"].as_u64() == Some(item.item_id))?;
    can_support_ability_focus(asset).then_some(target.ability_id)
}

fn can_support_ability_focus(asset: &Value) -> bool {
    if asset["type"] != "upgrade"
        || [
            "AmmoReloadPercent",
            "WeaponPowerPerStack",
            "BulletsBonusMagicDamage",
        ]
        .iter()
        .any(|property| has_positive_property(asset, property))
    {
        return false;
    }
    let properties: &[&str] = match asset["imbue"].as_str() {
        Some("imbue_modifier_value") => &[
            "TechRadiusMultiplier",
            "TechRangeMultiplier",
            "CooldownReduction",
            "BonusAbilityDurationPercent",
            "ImbuedCooldownReduction",
            "ImbuedTechPower",
            "ImbuedBonusDamage",
            "ImbuedBonusDuration",
        ],
        Some("imbue_active" | "imbue_active_non_ult") => &[
            "ImbuedTechPower",
            "ImbueAbilityLifesteal",
            "TechDamagePercent",
            "BonusAbilityCharges",
            "BonusAbilityChargesNonCharge",
            "ImbuedCooldownMultiplier",
        ],
        _ => return false,
    };
    properties
        .iter()
        .any(|property| has_positive_property(asset, property))
}

fn has_positive_property(asset: &Value, property: &str) -> bool {
    let value = &asset["properties"][property]["value"];
    value
        .as_f64()
        .or_else(|| value.as_str()?.parse::<f64>().ok())
        .is_some_and(|value| value.is_finite() && value > 0.0)
}
