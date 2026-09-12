use std::collections::BTreeMap;

use deadlock_data::{Error, Result, integer};
use deadlock_guides::{
    AbilityPath, BuildEvidenceCatalog, HeroBuildEvidence, PurchaseGuide, SelectedHeroBuild,
    parse_ability_definitions, schedule_ability_path, select_ability_path, select_hero_build,
    summarize_duration_distribution, validate_ability_timeline,
};
use deadlock_input::{DeadlockApi, build_hero_mechanics};
use serde_json::{Value, json};

use crate::generation_types::{CohortAnalytics, HeroInputs};

pub fn collect_cohort_analytics(api: &mut DeadlockApi, start: i64) -> Result<CohortAnalytics> {
    let duration = api.hero_stats_by_duration(start)?;
    let distribution = summarize_duration_distribution(&duration)?;
    let same_lane = group_matchups(api.hero_counter_stats(start, true)?, "same_lane");
    let whole_team = group_matchups(api.hero_counter_stats(start, false)?, "whole_enemy_team");
    Ok(CohortAnalytics {
        duration,
        distribution,
        same_lane,
        whole_team,
    })
}

fn group_matchups(rows: Vec<Value>, scope: &str) -> BTreeMap<u64, Vec<Value>> {
    let mut grouped = BTreeMap::<_, Vec<_>>::new();
    for mut row in rows {
        if let Some(id) = row["hero_id"]
            .as_u64()
            .filter(|_| row["enemy_hero_id"].as_u64().is_some())
        {
            row["scope"] = scope.into();
            row["unit"] = "hero_enemy_pair".into();
            grouped.entry(id).or_default().push(row);
        }
    }
    grouped
}

pub fn collect_hero_inputs(
    api: &mut DeadlockApi,
    heroes: &[Value],
    evidence: &BuildEvidenceCatalog,
    assets: &[Value],
    start: i64,
    analytics: &CohortAnalytics,
) -> Result<Vec<HeroInputs>> {
    let prepared = api.map_requests(heroes, 8, |api, hero| {
        let id = integer(hero, "id")?;
        let record = evidence
            .heroes()
            .get(&id)
            .ok_or_else(|| Error::new(format!("Hero {id} is missing build evidence")))?;
        if let Some(reason) = &record.exclusion {
            return Err(Error::new(format!(
                "Requested hero {id} has no supported build: {reason}"
            )));
        }
        let first = record
            .builds
            .first()
            .ok_or_else(|| Error::new("Hero has no admitted build"))?;
        let ranks = first.cohort.rank_range()?;
        let expanded = ranks != api.options().rank_range;
        api.with_rank_range(ranks, |api| {
            let scoped;
            let analytics = if expanded {
                scoped = collect_cohort_analytics(api, start)?;
                &scoped
            } else {
                analytics
            };
            prepare_hero(api, hero, &record.builds, assets, start, analytics)
        })
    })?;
    Ok(prepared.into_iter().flatten().collect())
}

fn prepare_hero(
    api: &mut DeadlockApi,
    hero: &Value,
    builds: &[HeroBuildEvidence],
    assets: &[Value],
    start: i64,
    analytics: &CohortAnalytics,
) -> Result<Vec<HeroInputs>> {
    let id = integer(hero, "id")?;
    let global = select_ability_path(&api.ability_order_stats(id, start, 1, &[])?, &[])?
        .ok_or_else(|| {
            Error::new(format!(
                "Hero {id} has no complete reached-state ability order"
            ))
        })?;
    let kit = build_hero_mechanics(hero, assets)?;
    let definitions = parse_ability_definitions(&kit)?;
    let mut inputs = Vec::new();
    for build in builds {
        let selected = select_hero_build(build, assets)?;
        validate_imbue_targets(&selected, &definitions)?;
        let ability = select_build_ability(api, &selected, start, &global)?;
        let actions =
            schedule_ability_path(&definitions, &kit["level_info"], &ability.ability_ids)?;
        let timeline = validate_ability_timeline(&definitions, &kit["level_info"], &actions)?;
        let guide = PurchaseGuide::from_selected(hero, &selected, Some(ability))?;
        if !guide.has_complete_item_coverage() {
            return Err(Error::new(format!(
                "Hero {id} has incomplete item coverage"
            )));
        }
        inputs.push(HeroInputs {
            selected,
            guide,
            kit: kit.clone(),
            timeline,
            duration: analytics.duration.get(&id).cloned().unwrap_or_default(),
            distribution: analytics.distribution.clone(),
            matchups: json!({"same_lane":analytics.same_lane.get(&id).cloned().unwrap_or_default(),
                "whole_enemy_team":analytics.whole_team.get(&id).cloned().unwrap_or_default()}),
            situational: build.situational_policy.clone(),
        });
    }
    Ok(inputs)
}

fn validate_imbue_targets(
    selected: &SelectedHeroBuild,
    definitions: &BTreeMap<u64, deadlock_guides::AbilityDefinition>,
) -> Result<()> {
    for item in selected
        .core
        .iter()
        .chain(&selected.core_purchase_path)
        .chain(&selected.optional_core)
        .chain(selected.tiers.values().flatten())
    {
        let item = item.content();
        if let Some(target) = item
            .imbue_target_ability_id
            .filter(|target| !definitions.contains_key(target))
        {
            return Err(Error::new(format!(
                "Item {} has an imbue target outside the current hero kit: {target}",
                item.item
            )));
        }
    }
    Ok(())
}

fn select_build_ability(
    api: &mut DeadlockApi,
    selected: &SelectedHeroBuild,
    start: i64,
    global: &AbilityPath,
) -> Result<AbilityPath> {
    let ids = selected
        .backbone
        .iter()
        .map(|item| item.content().item_id)
        .collect::<Vec<_>>();
    let filtered = select_ability_path(
        &api.ability_order_stats(selected.hero_id, start, 1, &ids)?,
        &ids,
    )?;
    if let Some(path) = &filtered
        && path.minimum_decision_support() >= 20
    {
        return Ok(path.clone());
    }
    let mut fallback = global.clone();
    fallback.fallback_reason = Some(
        if filtered.is_some() {
            "Build-conditioned ability order has a decision with fewer than 20 observations"
        } else {
            "Build-conditioned ability telemetry has no complete order"
        }
        .into(),
    );
    Ok(fallback)
}
