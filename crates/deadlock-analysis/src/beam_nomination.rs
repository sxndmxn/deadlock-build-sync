use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, array, integer};
use deadlock_guides::SUPPORT;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::beam_model::BeamModel;
use crate::beam_search::{BeamRoute, SearchRequest, search_group};
use crate::beam_support::{BeamOwnership, CoreGroups};
use crate::config::cohort_ranks;
use crate::core_discovery::core_identity;
use crate::core_outcomes::evaluate_core;
use crate::database::AnalysisDatabase;
use crate::discovery_data::{DiscoveryData, load_discovery_data};
use crate::discovery_models::{ExportContext, Nomination, item_ids};
use crate::mechanic_overlap::describe_overlap;
use crate::mining::Candidate;
use crate::purchase_orders::{order_evidence, replay_actions};
use crate::purchase_pool::freeze_guide;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BeamNomination {
    pub group: String,
    pub row: Nomination,
    pub scores: BTreeMap<String, f64>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HeroProposals {
    pub proposals: Vec<BeamNomination>,
    pub diagnostics: Vec<Value>,
}

pub fn core_items(build: &Value) -> Result<BTreeSet<u64>> {
    Ok(item_ids(&build["core_policy"]["default_item_ids"])?
        .into_iter()
        .collect())
}

pub fn baseline_groups(baseline: &Value) -> Result<Vec<(String, Vec<Value>)>> {
    let mut groups = BTreeMap::<String, Vec<Value>>::new();
    for build in array(&baseline["builds"])? {
        groups
            .entry(deadlock_data::text(build, "guide_group_id")?.into())
            .or_default()
            .push(build.clone());
    }
    let mut groups = groups.into_iter().collect::<Vec<_>>();
    groups.sort_by_key(|(_, builds)| {
        builds
            .iter()
            .filter_map(|build| build["discovery"]["selection_rank"].as_u64())
            .min()
    });
    Ok(groups)
}

pub fn discover_beam_hero(
    hero: &Value,
    baseline: &Value,
    context: &ExportContext,
) -> Result<HeroProposals> {
    let identifier = integer(hero, "id")?;
    let ranks = cohort_ranks(&baseline["cohort"])?;
    let database = context.open_database(identifier)?;
    let data = load_discovery_data(&database, identifier, &context.graph, ranks)?;
    let model = BeamModel::load(&database, &data, ranks)?;
    let grouped = baseline_groups(baseline)?;
    let groups = grouped
        .iter()
        .map(|(name, builds)| {
            Ok((
                name.clone(),
                builds.iter().map(core_items).collect::<Result<Vec<_>>>()?,
            ))
        })
        .collect::<Result<CoreGroups>>()?;
    let mut proposals = BTreeMap::<(String, Vec<u64>, Vec<u64>), BeamNomination>::new();
    let mut diagnostics = Vec::new();
    for state in [1, 0, 2] {
        let ownership = BeamOwnership::new(&data, &context.graph, state)?;
        for (group, builds) in &grouped {
            let default = builds
                .iter()
                .find(|build| build["path_id"] == *group)
                .ok_or_else(|| Error::new("Beam group has no default build"))?;
            let request = SearchRequest {
                graph: &context.graph,
                model: &model,
                ownership: &ownership,
                groups: &groups,
                group,
                state,
                candidates: &data.items,
            };
            let result = nominate_search(&database, hero, &data, &request, default, context)?;
            diagnostics.extend(result.diagnostics);
            for proposed in result.proposals {
                let key = (
                    proposed.group.clone(),
                    proposed.row.candidate.items.clone(),
                    proposed.row.guide.path.clone(),
                );
                if let Some(previous) = proposals.get_mut(&key) {
                    previous.scores.extend(proposed.scores);
                } else {
                    proposals.insert(key, proposed);
                }
            }
        }
    }
    eprintln!(
        "Beam proposals: {} ({} routes)",
        hero["name"].as_str().unwrap_or("hero"),
        proposals.len()
    );
    Ok(HeroProposals {
        proposals: proposals.into_values().collect(),
        diagnostics,
    })
}

fn nominate_search(
    database: &AnalysisDatabase,
    hero: &Value,
    data: &DiscoveryData,
    request: &SearchRequest<'_>,
    default: &Value,
    context: &ExportContext,
) -> Result<HeroProposals> {
    let result = search_group(request)?;
    let mut routes = result.routes;
    let default = core_items(default)?;
    routes.sort_by(|left, right| {
        right
            .score
            .total_cmp(&left.score)
            .then_with(|| {
                (left.core.iter().copied().collect::<BTreeSet<_>>() != default)
                    .cmp(&(right.core.iter().copied().collect::<BTreeSet<_>>() != default))
            })
            .then(right.owners.cmp(&left.owners))
            .then_with(|| left.core.cmp(&right.core))
            .then_with(|| left.path.cmp(&right.path))
    });
    let count = routes.len();
    let mut accepted = BTreeSet::new();
    let mut proposals = Vec::new();
    let mut rejected = BTreeMap::<String, u64>::new();
    for route in routes {
        if accepted.contains(&route.core) {
            continue;
        }
        match nominate_route(database, hero, data, &route, context) {
            Ok(row) => {
                accepted.insert(route.core);
                proposals.push(BeamNomination {
                    group: request.group.into(),
                    row,
                    scores: BTreeMap::from([(request.state.to_string(), route.score)]),
                });
            }
            Err(error) => *rejected.entry(error.to_string()).or_default() += 1,
        }
    }
    Ok(HeroProposals {
        proposals,
        diagnostics: vec![
            json!({"group":request.group,"state":request.state,"routes":count,"admitted_cores":accepted.len(),"rejections":rejected,"unassigned":result.unassigned,"expansions":result.expansions}),
        ],
    })
}

fn nominate_route(
    database: &AnalysisDatabase,
    hero: &Value,
    data: &DiscoveryData,
    route: &BeamRoute,
    context: &ExportContext,
) -> Result<Nomination> {
    let order = route
        .targets
        .iter()
        .filter(|item| route.core.contains(item))
        .copied()
        .collect::<Vec<_>>();
    let discovery_order = order_evidence(data, &route.core, &order, "discovery")?;
    let selection_order = order_evidence(data, &route.core, &order, "selection")?;
    if discovery_order["passes"] != true || selection_order["passes"] != true {
        return Err(Error::new(
            "Beam order lacks discovery or selection support",
        ));
    }
    let actions = replay_actions(&route.path, &route.core, &context.graph)?;
    if actions
        .last()
        .and_then(|step| step["cumulative_cost"].as_u64())
        != Some(route.spent)
    {
        return Err(Error::new(
            "Beam route differs from production mechanics replay",
        ));
    }
    let discovery = evaluate_core(data, &route.core, "discovery")?;
    let selection = evaluate_core(data, &route.core, "selection")?;
    let support = integer(&discovery, "owners")?;
    let reasons = SUPPORT.core_reasons(support, integer(&selection, "owners")?);
    if !reasons.is_empty() {
        return Err(Error::new(reasons.join("; ")));
    }
    let path = json!({"method":"beam16","order":order,"discovery":discovery_order,"selection":selection_order,"admitted_before_validation":true,"legal":true,"actions":actions,"reason":null});
    let names = route
        .core
        .iter()
        .map(|item| context.graph.require(*item).map(|node| node.name.clone()))
        .collect::<Result<Vec<_>>>()?;
    let cost = route
        .core
        .iter()
        .map(|item| context.graph.require(*item).map(|node| node.cost))
        .collect::<Result<Vec<_>>>()?
        .iter()
        .sum();
    let candidate = Candidate {
        items: route.core.clone(),
        names,
        cost,
        discovery_support: support,
        discovery_lift: deadlock_data::real(&discovery, "joint_lift")?,
        score: route.score,
        parent: Vec::new(),
        parent_retention: None,
        identity_id: core_identity(data.hero, &route.core),
        selection,
        selection_rejections: Vec::new(),
    };
    let guide = freeze_guide(
        database,
        data,
        &route.core,
        &order,
        &context.graph,
        Some(&route.path),
    )?;
    Ok(Nomination {
        candidate,
        hero_id: data.hero,
        selection_rank: 0,
        path,
        guide,
        tactics: describe_overlap(hero, &route.core, &context.normal_assets)?,
        branch_candidates: Vec::new(),
    })
}
