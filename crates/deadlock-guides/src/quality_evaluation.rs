use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Result, count_ratio, fingerprint};
use deadlock_input::ItemGraph;
use serde_json::{Value, json};

use crate::evidence_catalog::BuildEvidenceCatalog;
use crate::hero_evidence::HeroBuildEvidence;
use crate::inventory::{InventoryState, purchase_item};
use crate::policy_model::BuildPolicy;
use crate::quality_replay::ReplayCase;
use crate::recommendation::recommend;
use crate::recommendation_types::{Recommendation, RecommendationAction};

const MINIMUM_REPLAY_MATCHES: usize = 20;

#[derive(Debug)]
struct ReplayOutcome<'case> {
    case: &'case ReplayCase,
    action: &'static str,
    agreement: bool,
    baseline_agreement: bool,
    illegal_buy: bool,
}

impl ReplayOutcome<'_> {
    fn valid(&self) -> bool {
        self.action != "invalid"
    }
    fn covered(&self) -> bool {
        matches!(self.action, "buy" | "save" | "end")
    }
}

/// # Errors
/// Returns an error when item mechanics, policy serialization, or numeric summary calculations fail.
pub fn evaluate_policy(
    catalog: &BuildEvidenceCatalog,
    policy: &BuildPolicy,
    evidence: &HeroBuildEvidence,
    cases: &[ReplayCase],
    assets: &[Value],
) -> Result<Value> {
    let graph = if cases.is_empty() {
        None
    } else {
        Some(ItemGraph::from_assets(assets)?)
    };
    let mut outcomes = Vec::new();
    if let Some(graph) = &graph {
        for case in cases
            .iter()
            .filter(|case| case.policy_id == policy.policy_id())
        {
            outcomes.push(evaluate_case(
                catalog, policy, evidence, case, assets, graph,
            ));
        }
    }
    let strata = group_outcomes(&outcomes, evidence);
    let supported = strata.values().all(|rows| {
        rows.iter()
            .filter(|row| row.covered() && !row.case.ambiguous_purchase)
            .map(|row| &row.case.match_group)
            .collect::<BTreeSet<_>>()
            .len()
            >= MINIMUM_REPLAY_MATCHES
    });
    let failed = outcomes.iter().any(|row| !row.valid() || row.illegal_buy);
    let ranks = outcomes
        .iter()
        .map(|row| row.case.state.content().average_badge / 10)
        .collect::<BTreeSet<_>>();
    let rank_tiers = ranks
        .iter()
        .map(|rank| {
            Ok((
                rank.to_string(),
                summarize(
                    &outcomes
                        .iter()
                        .filter(|row| row.case.state.content().average_badge / 10 == *rank)
                        .collect::<Vec<_>>(),
                )?,
            ))
        })
        .collect::<Result<BTreeMap<_, _>>>()?;
    Ok(
        json!({"status":if failed {"fail"} else if supported {"pass"} else {"unevaluated"},
        "scope":"technical checks on exact runtime policy","policy_id":policy.policy_id(),"policy_sha256":fingerprint(&policy.to_document(true)?)?,
        "minimum_matches":MINIMUM_REPLAY_MATCHES,"reason":if failed {"Replay contains invalid states or illegal purchases"}
            else if supported {"Technical replay checks passed. Strategic superiority remains unproven"}
            else {"One or more required groups lack independent replay matches"},
        "summary":summarize(&outcomes.iter().collect::<Vec<_>>())?,"strata":strata.iter().map(|(name, rows)| Ok((*name, summarize(rows)?))).collect::<Result<BTreeMap<_, _>>>()?,
        "rank_tiers":rank_tiers,"claim":"The report measures action agreement, coverage, and legality. It does not establish item effects or improved match outcomes."}),
    )
}

fn evaluate_case<'case>(
    catalog: &BuildEvidenceCatalog,
    policy: &BuildPolicy,
    evidence: &HeroBuildEvidence,
    case: &'case ReplayCase,
    assets: &[Value],
    graph: &ItemGraph,
) -> ReplayOutcome<'case> {
    let Ok(decision) = recommend(catalog, policy, &case.state, assets) else {
        return ReplayOutcome {
            case,
            action: "invalid",
            agreement: false,
            baseline_agreement: false,
            illegal_buy: false,
        };
    };
    let buy = decision.action == RecommendationAction::Buy;
    let baseline = baseline_item(evidence, case, graph);
    ReplayOutcome {
        case,
        action: action_name(decision.action),
        agreement: decision.action == case.observed_action
            && (!buy || decision.item_id == case.observed_item_id),
        baseline_agreement: baseline.map_or(
            case.observed_action == RecommendationAction::Save,
            |id| {
                case.observed_action == RecommendationAction::Buy
                    && case.observed_item_id == Some(id)
            },
        ),
        illegal_buy: buy && !legal_buy(&decision, case, graph),
    }
}

const fn action_name(action: RecommendationAction) -> &'static str {
    match action {
        RecommendationAction::Buy => "buy",
        RecommendationAction::Save => "save",
        RecommendationAction::End => "end",
        RecommendationAction::Abstain => "abstain",
    }
}

fn baseline_item(
    evidence: &HeroBuildEvidence,
    case: &ReplayCase,
    graph: &ItemGraph,
) -> Option<u64> {
    let state = case.state.content();
    let inventory =
        InventoryState::new(state.inventory.items.clone(), state.inventory.flex_slots).ok()?;
    let mut items = evidence
        .items
        .iter()
        .map(crate::item_evidence::ItemEvidence::content)
        .collect::<Vec<_>>();
    items.sort_by_key(|item| {
        (
            std::cmp::Reverse(item.training_adopter_matches),
            item.item_id,
        )
    });
    items
        .into_iter()
        .find(|item| {
            item.training_adopter_matches >= 20
                && purchase_item(graph, &inventory, item.item_id, 0).is_ok()
                && graph
                    .incremental_cash_cost(item.item_id, inventory.owned())
                    .is_ok_and(|cost| cost <= state.liquid_souls)
        })
        .map(|item| item.item_id)
}

fn legal_buy(decision: &Recommendation, case: &ReplayCase, graph: &ItemGraph) -> bool {
    let state = case.state.content();
    let Some(id) = decision.item_id else {
        return false;
    };
    let Ok(inventory) =
        InventoryState::new(state.inventory.items.clone(), state.inventory.flex_slots)
    else {
        return false;
    };
    purchase_item(graph, &inventory, id, 0).is_ok()
        && graph
            .incremental_cash_cost(id, inventory.owned())
            .is_ok_and(|cost| cost <= state.liquid_souls && Some(cost) == decision.incremental_cost)
}

fn group_outcomes<'outcomes, 'case>(
    outcomes: &'outcomes [ReplayOutcome<'case>],
    evidence: &HeroBuildEvidence,
) -> BTreeMap<&'static str, Vec<&'outcomes ReplayOutcome<'case>>> {
    let path = &evidence.sequence_policy.content().default_path;
    let mut groups = BTreeMap::from([
        ("opening", Vec::new()),
        ("midgame", Vec::new()),
        ("late", Vec::new()),
        ("behind", Vec::new()),
        ("unfinished_core", Vec::new()),
        ("manual_deviation", Vec::new()),
    ]);
    for row in outcomes {
        let state = row.case.state.content();
        let phase = match state.clock_s {
            0..540 => "opening",
            540..1200 => "midgame",
            _ => "late",
        };
        groups.entry(phase).or_default().push(row);
        for (name, included) in [
            ("behind", row.case.behind),
            ("unfinished_core", !row.case.core_completed),
            (
                "manual_deviation",
                state.purchases.iter().any(|id| !path.contains(id)),
            ),
        ] {
            if included {
                groups.entry(name).or_default().push(row);
            }
        }
    }
    groups
}

fn summarize(outcomes: &[&ReplayOutcome<'_>]) -> Result<Value> {
    let usable = outcomes
        .iter()
        .copied()
        .filter(|row| row.valid())
        .collect::<Vec<_>>();
    let scored = usable
        .iter()
        .copied()
        .filter(|row| !row.case.ambiguous_purchase)
        .collect::<Vec<_>>();
    let mut actions = BTreeMap::<&str, usize>::new();
    for row in &usable {
        *actions.entry(row.action).or_default() += 1;
    }
    Ok(
        json!({"decisions":outcomes.len(),"matches":usable.iter().map(|row| &row.case.match_group).collect::<BTreeSet<_>>().len(),
        "invalid_states":outcomes.len() - usable.len(),"illegal_buys":outcomes.iter().filter(|row| row.illegal_buy).count(),"actions":actions,
        "decision_coverage":ratio(usable.iter().filter(|row| row.covered()).count(), outcomes.len())?,
        "affordable_buy_share":ratio(actions.get("buy").copied().unwrap_or(0), usable.len())?,
        "scored_decisions":scored.len(),"ambiguous_decisions":usable.len() - scored.len(),
        "top1_action_agreement":ratio(scored.iter().filter(|row| row.agreement).count(), scored.len())?,
        "training_popularity_top1":ratio(scored.iter().filter(|row| row.baseline_agreement).count(), scored.len())?}),
    )
}

fn ratio(numerator: usize, denominator: usize) -> Result<Option<f64>> {
    if denominator == 0 {
        Ok(None)
    } else {
        Ok(Some(count_ratio(
            u64::try_from(numerator)?,
            u64::try_from(denominator)?,
        )?))
    }
}
