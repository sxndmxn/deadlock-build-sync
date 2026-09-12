use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{
    Error, Result, array, atomic_write_json, fingerprint, integer, text, trace_operation,
};
use deadlock_guides::beam_generator_record;
use serde_json::{Value, json};

use crate::beam_admission::validate_complete_guide;
use crate::beam_nomination::{
    BeamNomination, HeroProposals, baseline_groups, core_items, discover_beam_hero,
};
use crate::beam_support::state_statistics;
use crate::build_payload::build_payload;
use crate::config::{cohort_ranks, implementation_record};
use crate::core_discovery::core_identity;
use crate::discovery_admission::admit_nomination;
use crate::discovery_data::{DiscoveryData, load_discovery_data};
use crate::discovery_models::{ExportContext, item_ids};
use crate::discovery_snapshot::{require_source_identity, source_identity};
use deadlock_data::map_jobs;

pub fn generate_beam_roster(
    heroes: &[Value],
    baseline: &[Value],
    context: &ExportContext,
    workers: u16,
) -> Result<Vec<Value>> {
    let source = source_identity(&context.paths)?;
    let by_id = heroes
        .iter()
        .map(|hero| Ok((integer(hero, "id")?, hero)))
        .collect::<Result<BTreeMap<_, _>>>()?;
    let proposals = trace_operation(
        "analysis.freeze_beam_roster",
        Some("freeze_beam_roster"),
        || {
            map_jobs(baseline, workers, |row| {
                discover_beam_hero(by_id[&integer(row, "hero_id")?], row, context)
            })
        },
    )?;
    let frozen = freeze_proposals(baseline, &proposals, &source)?;
    let digest = fingerprint(&frozen)?;
    atomic_write_json(
        &context
            .paths
            .run
            .join(format!("beam-nominations-{}.json", &digest[..16])),
        &frozen,
    )?;
    let diagnostics = baseline
        .iter()
        .zip(&proposals)
        .map(|(hero, result)| {
            Ok((
                integer(hero, "hero_id")?.to_string(),
                result.diagnostics.clone(),
            ))
        })
        .collect::<Result<BTreeMap<_, _>>>()?;
    atomic_write_json(
        &context
            .paths
            .run
            .join(format!("beam-diagnostics-{}.json", &digest[..16])),
        &serde_json::to_value(diagnostics)?,
    )?;
    let family = u64::try_from(
        proposals
            .iter()
            .map(|result| result.proposals.len())
            .sum::<usize>()
            .max(1),
    )?;
    let jobs = baseline.iter().zip(&proposals).collect::<Vec<_>>();
    let result = trace_operation(
        "analysis.validate_beam_roster",
        Some("validate_beam_roster"),
        || {
            map_jobs(&jobs, workers, |(baseline, proposals)| {
                validate_beam_hero(
                    by_id[&integer(baseline, "hero_id")?],
                    baseline,
                    proposals,
                    context,
                    family,
                    &digest,
                )
            })
        },
    )?;
    require_source_identity(&context.paths, &source)?;
    Ok(result)
}

fn freeze_proposals(
    baseline: &[Value],
    proposals: &[HeroProposals],
    source: &Value,
) -> Result<Value> {
    let mut heroes = BTreeMap::new();
    for (hero, result) in baseline.iter().zip(proposals) {
        let groups = baseline_groups(hero)?
            .into_iter()
            .map(|(group, builds)| {
                Ok((
                    group,
                    builds.iter().map(core_items).collect::<Result<Vec<_>>>()?,
                ))
            })
            .collect::<Result<BTreeMap<_, _>>>()?;
        heroes.insert(
            integer(hero, "hero_id")?.to_string(),
            json!({"proposals":result.proposals,"groups":groups}),
        );
    }
    Ok(
        json!({"generator":beam_generator_record()?,"implementation":implementation_record(),"source_identity":source,"baseline_sha256":fingerprint(&serde_json::to_value(baseline)?)?,"order_only":false,"heroes":heroes}),
    )
}

fn preferred_proposals(rows: &[BeamNomination]) -> Result<Vec<&BeamNomination>> {
    let mut rows = rows
        .iter()
        .map(|row| Ok((row, item_ids(&row.row.path["order"])?)))
        .collect::<Result<Vec<_>>>()?;
    let score = |row: &BeamNomination| {
        row.scores.get("1").copied().unwrap_or_else(|| {
            row.scores
                .values()
                .copied()
                .fold(f64::NEG_INFINITY, f64::max)
        })
    };
    rows.sort_by(|(left, left_order), (right, right_order)| {
        (!left.scores.contains_key("1"))
            .cmp(&!right.scores.contains_key("1"))
            .then_with(|| score(right).total_cmp(&score(left)))
            .then(
                right
                    .row
                    .candidate
                    .discovery_support
                    .cmp(&left.row.candidate.discovery_support),
            )
            .then_with(|| left.row.candidate.items.cmp(&right.row.candidate.items))
            .then_with(|| left_order.cmp(right_order))
    });
    let mut seen = BTreeSet::new();
    rows.retain(|(row, _)| seen.insert(&row.row.candidate.identity_id));
    Ok(rows.into_iter().map(|(row, _)| row).collect())
}

fn validate_beam_hero(
    hero: &Value,
    baseline: &Value,
    proposals: &HeroProposals,
    context: &ExportContext,
    family: u64,
    digest: &str,
) -> Result<Value> {
    let identifier = integer(hero, "id")?;
    let database = context.open_database(identifier)?;
    let ranks = cohort_ranks(&baseline["cohort"])?;
    let data = load_discovery_data(&database, identifier, &context.graph, ranks)?;
    let groups = baseline_groups(baseline)?;
    let mut admitted_builds = BTreeMap::<String, Vec<Value>>::new();
    let mut rejected = Vec::new();
    for candidate in preferred_proposals(&proposals.proposals)? {
        let mut admitted = admit_nomination(&data, &candidate.row, family, digest)?;
        if !array(&admitted["rejections"])?.is_empty() {
            rejected
                .push(json!({"variant":admitted["identity_id"],"reasons":admitted["rejections"]}));
            continue;
        }
        admitted["automatic_choices"] = json!({"version":1,"branches":[]});
        let mut build = build_payload(&database, &data, &admitted, &context.assets)?;
        build["discovery"]["method"] = "eclat_leiden_beam".into();
        if let Err(error) = validate_complete_guide(
            &mut build,
            hero,
            &baseline["cohort"],
            context,
            &candidate.group,
        ) {
            rejected.push(json!({"variant":admitted["identity_id"],"reasons":[error.to_string()]}));
            continue;
        }
        let states = candidate
            .scores
            .keys()
            .map(|state| {
                state
                    .parse::<u8>()
                    .map_err(|error| Error::new(error.to_string()))
            })
            .collect::<Result<Vec<_>>>()?;
        let evidence = states
            .iter()
            .map(|state| {
                Ok((
                    state.to_string(),
                    state_statistics(&data, &candidate.row.candidate.items, *state)?,
                ))
            })
            .collect::<Result<BTreeMap<_, _>>>()?;
        build["generator"] = json!({"effective":"beam","states":states,"scores":candidate.scores,"state_evidence":evidence});
        admitted_builds
            .entry(candidate.group.clone())
            .or_default()
            .push(build);
    }
    let builds = assemble_hero(&data, groups, &mut admitted_builds, digest)?;
    let mut result = baseline.clone();
    result["builds"] = builds.into();
    result["beam_rejections"] = rejected.into();
    Ok(result)
}

fn assemble_hero(
    data: &DiscoveryData,
    groups: Vec<(String, Vec<Value>)>,
    admitted_builds: &mut BTreeMap<String, Vec<Value>>,
    digest: &str,
) -> Result<Vec<Value>> {
    let mut builds = Vec::new();
    for (group, baseline) in groups {
        let proposed = admitted_builds.entry(group.clone()).or_default();
        sort_proposals(proposed, &baseline, &group)?;
        let mut members = assemble_group(&baseline, proposed, &group)?;
        for member in &mut members {
            if member["generator"]["effective"] == "current" {
                member["generator"]["state_evidence"] = json!({"1":state_statistics(data,&core_items(member)?.into_iter().collect::<Vec<_>>(),1)?});
            }
        }
        let first = members
            .first()
            .ok_or_else(|| Error::new("Beam group has no complete admitted guide"))?;
        let default = core_identity(
            data.hero,
            &core_items(first)?.into_iter().collect::<Vec<_>>(),
        );
        attach_metadata(
            &mut members,
            data.hero,
            &group,
            &default,
            digest,
            builds.len(),
        )?;
        builds.extend(members);
    }
    Ok(builds)
}

fn sort_proposals(proposed: &mut [Value], baseline: &[Value], group: &str) -> Result<()> {
    let default = baseline
        .iter()
        .find(|build| build["path_id"] == group)
        .ok_or_else(|| Error::new("Beam group has no baseline default"))?;
    let default = core_items(default)?;
    let mut keys = BTreeMap::new();
    for build in proposed.iter() {
        keys.insert(
            text(build, "path_id")?.to_owned(),
            (
                !build["generator"]["scores"]
                    .as_object()
                    .is_some_and(|scores| scores.contains_key("1")),
                deadlock_data::real(&build["discovery"], "score")?,
                core_items(build)? != default,
                integer(&build["discovery"], "discovery_support")?,
            ),
        );
    }
    proposed.sort_by(|left, right| {
        let first = &keys[left["path_id"].as_str().unwrap_or_default()];
        let second = &keys[right["path_id"].as_str().unwrap_or_default()];
        first
            .0
            .cmp(&second.0)
            .then_with(|| second.1.total_cmp(&first.1))
            .then(first.2.cmp(&second.2))
            .then(second.3.cmp(&first.3))
            .then_with(|| left["path_id"].as_str().cmp(&right["path_id"].as_str()))
    });
    Ok(())
}

fn assemble_group(baseline: &[Value], proposed: &[Value], group: &str) -> Result<Vec<Value>> {
    if let Some(default) = proposed.iter().position(|build| {
        build["generator"]["states"]
            .as_array()
            .is_some_and(|states| states.contains(&1.into()))
    }) {
        return Ok(std::iter::once(proposed[default].clone())
            .chain(
                proposed
                    .iter()
                    .enumerate()
                    .filter(|(index, _)| *index != default)
                    .map(|(_, build)| build.clone()),
            )
            .collect());
    }
    let mut fallback = baseline.to_vec();
    fallback.sort_by_key(|build| build["path_id"] != group);
    for build in &mut fallback {
        build["generator"] = json!({"effective":"current","states":[1],"fallback_reason":"No complete admitted even-state beam guide exists in this group"});
    }
    let cores = fallback
        .iter()
        .map(core_items)
        .collect::<Result<BTreeSet<_>>>()?;
    for build in proposed {
        if !cores.contains(&core_items(build)?) {
            fallback.push(build.clone());
        }
    }
    Ok(fallback)
}

fn attach_metadata(
    members: &mut [Value],
    hero: u64,
    group: &str,
    default: &str,
    digest: &str,
    rank_start: usize,
) -> Result<()> {
    for (index, build) in members.iter_mut().enumerate() {
        let core = core_items(build)?.into_iter().collect::<Vec<_>>();
        let variant = core_identity(hero, &core);
        build["path_id"] = if index == 0 {
            group.into()
        } else {
            format!("{variant}-variant")
        }
        .into();
        build["guide_group_id"] = group.into();
        for (name, value) in [
            ("group_id", json!(group)),
            ("variant_id", json!(variant)),
            ("default_variant_id", json!(default)),
            ("baseline_path_id", json!(group)),
            ("core", json!(core)),
            ("frozen_sha256", json!(digest)),
        ] {
            build["generator"][name] = value;
        }
        build["discovery"]["selection_rank"] = (rank_start + index).into();
    }
    Ok(())
}
