use deadlock_data::{Error, Result, sha256};
use deadlock_guides::{HeroBuild, HeroBuildCatalog, assign_build_focus, build_hero_presentation};
use serde_json::{Value, json};

pub fn check_build_focus() -> Result<()> {
    let mut catalog: HeroBuildCatalog = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/imbue-catalog.json"
    ))?;
    let assets = reference_assets();
    let build = &mut catalog.heroes[0];
    build.core[0]
        .imbue_target
        .as_mut()
        .ok_or_else(|| Error::new("Reference target is missing"))?
        .ability_id = 102;
    assign_build_focus(build, &assets)?;
    require_focus(build, Some(102))?;
    let selected = build.clone();
    assign_build_focus(build, &assets)?;
    if selected != *build {
        return Err(Error::new("Repeated focus selection changes the build"));
    }
    catalog.validate()?;
    let root = tempfile::tempdir()?;
    let path = root.path().join("hero-builds.json");
    catalog.write(&path)?;
    if HeroBuildCatalog::read(&path)? != catalog {
        return Err(Error::new(
            "Catalog serialization changed the ability focus",
        ));
    }
    check_presentation(&catalog)?;
    check_rejected_focus(&catalog.heroes[0], &assets)?;
    check_upgrade_title(&catalog, &assets)?;
    check_focus_support(&catalog.heroes[0], &assets)?;
    check_title_limits(&catalog, &assets)?;
    check_invalid_focus(&catalog)
}

fn reference_assets() -> Vec<Value> {
    vec![
        json!({"id":10,"type":"upgrade","imbue":"imbue_active","properties":{"TechDamagePercent":{"value":"50"}}}),
        json!({"id":16,"type":"upgrade"}),
        json!({"id":17,"type":"upgrade","imbue":"imbue_modifier_value","properties":{"CooldownReduction":{"value":18}}}),
        json!({"id":101,"type":"ability","hero":1,"name":"Reference ability"}),
        json!({"id":102,"type":"ability","heroes":[1],"name":"Focus ability"}),
    ]
}

fn check_presentation(catalog: &HeroBuildCatalog) -> Result<()> {
    let build = &catalog.heroes[0];
    let presentation =
        build_hero_presentation(build, catalog, &sha256(b"focus reference"), "Player")?;
    let content = presentation.content();
    if content.name != "Player | Focus ability + Reference core item"
        || content.tag_ids[0] != 102
        || !content
            .description
            .contains("Play around: Focus ability with Reference core item")
        || !content
            .description
            .contains("Ability order: max Reference ability first.")
        || content.description.contains("max Focus ability first")
        || content.name.contains(&build.hero_name)
    {
        return Err(Error::new(
            "Presentation confuses ability focus, upgrade order, or hero name",
        ));
    }
    Ok(())
}

fn check_rejected_focus(build: &HeroBuild, assets: &[Value]) -> Result<()> {
    for (field, value) in [
        (
            "properties",
            json!({"TechDamagePercent":{"value":50},"AmmoReloadPercent":{"value":"100"}}),
        ),
        (
            "properties",
            json!({"TechDamagePercent":{"value":50},"WeaponPowerPerStack":{"value":20}}),
        ),
        ("properties", json!({"TechDamagePercent":{"value":"0"}})),
        ("properties", json!({"TechDamagePercent":{"value":"NaN"}})),
        ("properties", json!({})),
        ("imbue", json!("unknown")),
    ] {
        let mut assets = assets.to_vec();
        assets[0][field] = value;
        let mut selected = build.clone();
        assign_build_focus(&mut selected, &assets)?;
        require_focus(&selected, None)?;
        if selected.title != "Reference ability + Reference core item" || selected.tag_ids[0] != 101
        {
            return Err(Error::new(
                "Unclear focus did not use the ability upgrade title and icon",
            ));
        }
    }
    let mut assets = assets.to_vec();
    assets[4]["heroes"] = json!([2]);
    let mut selected = build.clone();
    assign_build_focus(&mut selected, &assets)?;
    require_focus(&selected, None)
}

fn check_upgrade_title(catalog: &HeroBuildCatalog, assets: &[Value]) -> Result<()> {
    let mut build = catalog.heroes[0].clone();
    for item in &mut build.core {
        item.imbue_target = None;
    }
    assign_build_focus(&mut build, assets)?;
    require_focus(&build, None)?;
    let presentation =
        build_hero_presentation(&build, catalog, &sha256(b"upgrade title"), "Player")?;
    let content = presentation.content();
    if content.name != "Player | Reference ability + Reference core item"
        || !content
            .description
            .contains("Play around: Reference core item")
        || !content
            .description
            .contains("Ability order: max Reference ability first.")
        || content.name.contains(&build.hero_name)
    {
        return Err(Error::new("Upgrade title changed the inferred build focus"));
    }
    for has_complete_order in [false, true] {
        let mut unsupported = build.clone();
        if has_complete_order {
            unsupported.key_ability_name = None;
        } else {
            unsupported.ability_ids.clear();
        }
        assign_build_focus(&mut unsupported, assets)?;
        if unsupported.title != "Reference core item" {
            return Err(Error::new(
                "Build title used an unsupported upgrade ability",
            ));
        }
    }
    Ok(())
}

fn check_focus_support(build: &HeroBuild, assets: &[Value]) -> Result<()> {
    let mut selected = build.clone();
    selected.key_item_id = 16;
    assign_build_focus(&mut selected, assets)?;
    require_focus(&selected, None)?;
    for ability in &mut selected.ability_ids {
        *ability = match *ability {
            101 => 102,
            102 => 101,
            other => other,
        };
    }
    assign_build_focus(&mut selected, assets)?;
    require_focus(&selected, Some(102))?;
    selected.ability_ids.clone_from(&build.ability_ids);
    let second = selected.situational.remove(0);
    selected.core.push(second);
    assign_build_focus(&mut selected, assets)?;
    require_focus(&selected, Some(102))?;
    selected.core[2]
        .imbue_target
        .as_mut()
        .ok_or_else(|| Error::new("Reference target is missing"))?
        .ability_id = 101;
    assign_build_focus(&mut selected, assets)?;
    require_focus(&selected, None)
}

fn check_title_limits(catalog: &HeroBuildCatalog, assets: &[Value]) -> Result<()> {
    let mut assets = assets.to_vec();
    assets[4]["name"] = json!("Ability");
    for (length, uses_ability) in [(40, true), (41, false)] {
        let mut build = catalog.heroes[0].clone();
        build.core[0].name = "é".repeat(length);
        assign_build_focus(&mut build, &assets)?;
        let presentation =
            build_hero_presentation(&build, catalog, &sha256(b"title reference"), "Player")?;
        let name = &presentation.content().name;
        if name.chars().count() > 50 || name.contains("Ability +") != uses_ability {
            return Err(Error::new("Build title does not apply the character limit"));
        }
    }
    Ok(())
}

fn check_invalid_focus(catalog: &HeroBuildCatalog) -> Result<()> {
    for ids in [vec![], vec![10, 10], vec![16], vec![17], vec![999]] {
        let mut invalid = catalog.clone();
        invalid.heroes[0]
            .ability_focus
            .as_mut()
            .ok_or_else(|| Error::new("Reference focus is missing"))?
            .supporting_item_ids = ids;
        if invalid.validate().is_ok() {
            return Err(Error::new("Catalog accepted an unsupported ability focus"));
        }
    }
    let mut old = catalog.clone();
    old.schema_version = 4;
    if old.validate().is_ok() {
        return Err(Error::new(
            "Catalog accepted the schema without ability focus",
        ));
    }
    Ok(())
}

fn require_focus(build: &HeroBuild, expected: Option<u64>) -> Result<()> {
    if build.ability_focus.as_ref().map(|focus| focus.ability_id) != expected {
        return Err(Error::new(
            "Ability focus does not match its supporting evidence",
        ));
    }
    Ok(())
}
