use deadlock_data::{Result, integer, trace_operation};
use serde_json::{Value, json};

use crate::ability_prefetch::AbilityPrefetch;
use crate::branch_evaluation::BranchEvaluator;
use crate::build_payload::build_payload;
use crate::checkpoint_data::load_checkpoints;
use crate::core_discovery::{assign_group_ids, freeze_hero};
use crate::discovery_admission::admit_nomination;
use crate::discovery_data::load_discovery_data;
use crate::discovery_models::{ExportContext, FrozenHero};
use crate::discovery_snapshot::{
    FrozenRoster, GuideGroups, load_snapshot, require_source_identity, roster_fingerprint,
    save_snapshot, source_identity,
};
use deadlock_data::{map_jobs, map_jobs_by_cost};

pub fn discover_roster(
    heroes: &[Value],
    context: &ExportContext,
    workers: u16,
    resume: bool,
    prefetch: &AbilityPrefetch,
) -> Result<Vec<Value>> {
    let source = source_identity(&context.paths)?;
    let (frozen, groups) = if resume {
        load_snapshot(&context.paths, heroes)?
    } else {
        let reports = trace_operation("analysis.freeze_roster", Some("freeze_roster"), || {
            map_jobs(heroes, workers, |hero| freeze_hero(hero, context))
        })?;
        let frozen = heroes
            .iter()
            .zip(reports)
            .map(|(hero, report)| Ok((integer(hero, "id")?, report)))
            .collect::<Result<FrozenRoster>>()?;
        let groups = frozen
            .iter()
            .map(|(hero, report)| Ok((*hero, assign_group_ids(&report.rows)?)))
            .collect::<Result<GuideGroups>>()?;
        save_snapshot(&context.paths, &frozen, &groups, &source)?;
        (frozen, groups)
    };
    let family = u64::try_from(
        frozen
            .values()
            .map(|report| report.rows.len())
            .sum::<usize>()
            .max(1),
    )?;
    let branches = u64::try_from(
        frozen
            .values()
            .flat_map(|report| &report.rows)
            .map(|row| row.branch_candidates.len())
            .sum::<usize>()
            .max(1),
    )?;
    let digest = roster_fingerprint(&frozen)?;
    let jobs = heroes
        .iter()
        .map(|hero| Ok((validation_cost(&frozen[&integer(hero, "id")?])?, hero)))
        .collect::<Result<Vec<_>>>()?;
    let result = std::thread::scope(|scope| {
        let pending = scope.spawn(|| {
            trace_operation(
                "analysis.prefetch_abilities",
                Some("prefetch_abilities"),
                || prefetch.collect(&frozen),
            )
        });
        let result = trace_operation("analysis.validate_roster", Some("validate_roster"), || {
            map_jobs_by_cost(
                &jobs,
                workers,
                |(cost, _)| *cost,
                |(_, hero)| {
                    let id = integer(hero, "id")?;
                    validate_hero(
                        hero,
                        &frozen[&id],
                        context,
                        (family, branches),
                        &digest,
                        &groups[&id],
                    )
                },
            )
        });
        match pending.join() {
            Ok(Ok(())) => {}
            Ok(Err(error)) => eprintln!(
                "Ability prefetch failed. Guide generation will request missing responses: {error}"
            ),
            Err(_) => eprintln!(
                "Ability prefetch stopped. Guide generation will request missing responses."
            ),
        }
        result
    })?;
    require_source_identity(&context.paths, &source)?;
    Ok(result)
}

fn validation_cost(report: &FrozenHero) -> Result<u64> {
    report.rows.iter().try_fold(0_u64, |total, row| {
        let candidates = u64::try_from(row.branch_candidates.len())?;
        Ok(total.saturating_add(candidates.saturating_mul(row.candidate.discovery_support)))
    })
}

fn validate_hero(
    hero: &Value,
    report: &FrozenHero,
    context: &ExportContext,
    families: (u64, u64),
    digest: &str,
    groups: &std::collections::BTreeMap<String, String>,
) -> Result<Value> {
    let identifier = integer(hero, "id")?;
    eprintln!("Validating {}", hero["name"].as_str().unwrap_or("hero"));
    let database = context.open_database(identifier)?;
    let ranks = crate::config::cohort_ranks(&report.cohort)?;
    let data = load_discovery_data(&database, identifier, &context.graph, ranks)?;
    let reviewed = report
        .rows
        .iter()
        .map(|row| admit_nomination(&data, row, families.0, digest))
        .collect::<Result<Vec<_>>>()?;
    let decisions = if report
        .rows
        .iter()
        .any(|row| !row.branch_candidates.is_empty())
    {
        load_checkpoints(
            &database,
            identifier,
            &context.graph,
            ranks.minimum.badge(),
            ranks.maximum.badge(),
        )?
    } else {
        Vec::new()
    };
    let mut evaluator = BranchEvaluator::new(&decisions);
    let mut builds = Vec::new();
    let mut rejections = Vec::new();
    for (nominee, admitted) in report.rows.iter().zip(&reviewed) {
        if admitted["rejections"]
            .as_array()
            .is_none_or(|reasons| !reasons.is_empty())
        {
            rejections
                .push(json!({"path_id":admitted["identity_id"],"reasons":admitted["rejections"]}));
            continue;
        }
        let mut admitted = admitted.clone();
        admitted["automatic_choices"] =
            evaluator.evaluate(nominee, &reviewed, &context.graph, families.1)?;
        let mut build = build_payload(&database, &data, &admitted, &context.assets)?;
        build["guide_group_id"] = groups[&nominee.candidate.identity_id].clone().into();
        builds.push(build);
    }
    let exclusion = if builds.is_empty() {
        json!({"code":"no_validated_identity","reason":"No supported legal build exists in the attempted rank ranges","candidate_count":report.candidate_count,
        "fold_observations":{"discovery":data.fold_rows("discovery").count(),"selection":data.fold_rows("selection").count(),"validation":data.fold_rows("validation").count()},
        "candidate_rejections":if rejections.is_empty(){report.candidates.iter().map(|row|json!({"items":row.items,"reasons":row.selection_rejections})).collect::<Vec<_>>()}else{rejections.clone()}})
    } else {
        Value::Null
    };
    Ok(
        json!({"cohort":report.cohort,"hero_id":identifier,"hero":hero["name"],"builds":builds,"exclusion":exclusion,"path_abstentions":rejections}),
    )
}
