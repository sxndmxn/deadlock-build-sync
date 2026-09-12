use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, array, object};
use serde_json::Value;

use crate::automatic_branch::{AutomaticBranch, parse_automatic_branches};
use crate::core_evidence::{CorePolicyEvidence, parse_distinct_ids};
use crate::discovery_evidence::{exclusion_reason, validate_discovery};
use crate::evidence_values::{add_counts, integer, nonempty_text};
use crate::frozen_pool::validate_frozen_pool;
use crate::generator_evidence::GeneratorEvidence;
use crate::hero_cohort::HeroCohort;
use crate::item_evidence::ItemEvidence;
use crate::purchase_timing::{PurchaseTiming, parse_purchase_timing};
use crate::sequence_evidence::{SequencePolicy, SequenceProduction};
use crate::situational_evidence::SituationalPolicy;
use crate::tier_evidence::TierPolicyEvidence;

#[derive(Clone, Debug)]
pub struct HeroBuildEvidence {
    pub hero_id: u64,
    pub hero: String,
    pub eligible_player_matches: u64,
    pub selection_eligible_player_matches: u64,
    pub fold_eligible_player_matches: BTreeMap<String, u64>,
    pub median_final_net_worth: Option<u64>,
    pub items: Vec<ItemEvidence>,
    pub core_policy: CorePolicyEvidence,
    pub tier_policy: TierPolicyEvidence,
    pub sequence_policy: SequencePolicy,
    pub situational_policy: SituationalPolicy,
    pub path_id: String,
    pub path_label: String,
    pub signature_item_ids: Vec<u64>,
    pub discovery: Value,
    pub purchase_timing: Vec<PurchaseTiming>,
    pub automatic_branches: Vec<AutomaticBranch>,
    pub cohort: HeroCohort,
    pub guide_group_id: String,
    pub generator: Option<GeneratorEvidence>,
}

#[derive(Clone, Debug)]
pub struct HeroEvidence {
    pub hero_id: u64,
    pub hero: String,
    pub builds: Vec<HeroBuildEvidence>,
    pub exclusion: Option<String>,
}

impl HeroEvidence {
    /// # Errors
    /// Returns an error when a hero has incomplete, duplicate, or unsupported build evidence.
    pub fn from_document(value: &Value) -> Result<Self> {
        object(value)?;
        let hero_id = integer(&value["hero_id"], "hero identifier", 1)?;
        let hero = nonempty_text(&value["hero"], "hero name")?.to_owned();
        let rows = array(&value["builds"])?;
        if rows.is_empty() {
            return Ok(Self {
                hero_id,
                hero,
                builds: Vec::new(),
                exclusion: Some(exclusion_reason(&value["exclusion"])?),
            });
        }
        if !value["exclusion"].is_null() {
            return Err(Error::new(
                "Hero has conflicting build admission and exclusion",
            ));
        }
        let cohort = HeroCohort::from_document(&value["cohort"])?;
        let builds = rows
            .iter()
            .map(|value| parse_build_path(value, hero_id, &hero, &cohort))
            .collect::<Result<Vec<_>>>()?;
        validate_build_identities(&builds)?;
        Ok(Self {
            hero_id,
            hero,
            builds,
            exclusion: None,
        })
    }
}

fn parse_build_path(
    value: &Value,
    hero_id: u64,
    hero_name: &str,
    cohort: &HeroCohort,
) -> Result<HeroBuildEvidence> {
    object(value)?;
    let path_id = nonempty_text(&value["path_id"], "build path identifier")?.to_owned();
    let path_label = nonempty_text(&value["path_label"], "build path label")?.to_owned();
    let signature_item_ids = parse_distinct_ids(&value["signature_item_ids"])?;
    let discovery = &value["discovery"];
    object(discovery)?;
    let (eligible, selection, folds) = parse_path_cohort(value)?;
    let items = parse_path_items(&value["items"], eligible, selection, &folds)?;
    let item_ids = items
        .iter()
        .map(|item| item.content().item_id)
        .collect::<BTreeSet<_>>();
    let core_policy =
        CorePolicyEvidence::from_document(&value["core_policy"], &item_ids, eligible)?;
    let sequence_policy = SequencePolicy::from_document(&value["sequence_policy"])?;
    let situational_policy = SituationalPolicy::from_document(&value["situational_policy"])?;
    let tier_policy = TierPolicyEvidence::from_document(&value["tier_policy"], &items)?;
    validate_policy_references(&core_policy, &sequence_policy, &situational_policy, &items)?;
    validate_discovery(
        discovery,
        &core_policy.content().default_item_ids,
        &sequence_policy.content().default_path,
    )?;
    if (sequence_policy.content().production_model == SequenceProduction::Beam16)
        != (discovery["method"].as_str() == Some("eclat_leiden_beam"))
    {
        return Err(Error::new(
            "Sequence generator differs from its discovery method",
        ));
    }
    validate_frozen_pool(value, discovery)?;
    let guide_group_id =
        nonempty_text(&value["guide_group_id"], "guide group identifier")?.to_owned();
    let generator = value
        .get("generator")
        .map(|value| {
            GeneratorEvidence::from_document(
                value,
                &guide_group_id,
                &core_policy.content().default_item_ids,
                hero_id,
            )
        })
        .transpose()?;
    let median_final_net_worth = value
        .get("median_final_net_worth")
        .filter(|value| !value.is_null())
        .map(|value| integer(value, "median final net worth", 1))
        .transpose()?;
    let pool = tier_policy
        .item_ids_by_tier()
        .values()
        .flatten()
        .copied()
        .collect();
    let automatic_branches = parse_automatic_branches(
        &value["automatic_choices"],
        &pool,
        &sequence_policy.content().default_path,
    )?;
    let purchase_timing = parse_purchase_timing(
        &value["purchase_timing"],
        &sequence_policy,
        &tier_policy,
        &items,
    )?;
    Ok(HeroBuildEvidence {
        hero_id,
        hero: hero_name.into(),
        eligible_player_matches: eligible,
        selection_eligible_player_matches: selection,
        fold_eligible_player_matches: folds,
        median_final_net_worth,
        items,
        core_policy,
        tier_policy,
        sequence_policy,
        situational_policy,
        path_id,
        path_label,
        signature_item_ids,
        discovery: discovery.clone(),
        purchase_timing,
        automatic_branches,
        cohort: cohort.clone(),
        guide_group_id,
        generator,
    })
}

fn parse_path_cohort(value: &Value) -> Result<(u64, u64, BTreeMap<String, u64>)> {
    let eligible = integer(
        &value["eligible_player_matches"],
        "eligible player matches",
        1,
    )?;
    let selection = integer(
        &value["selection_eligible_player_matches"],
        "selection eligible player matches",
        1,
    )?;
    let raw = &value["fold_eligible_player_matches"];
    object(raw)?;
    let mut folds = BTreeMap::new();
    for fold in ["train", "validation", "test"] {
        folds.insert(
            fold.into(),
            integer(
                &raw[fold],
                "fold eligible player matches",
                u64::from(fold == "train"),
            )?,
        );
    }
    if add_counts(folds["train"], folds["validation"])? != selection
        || add_counts(selection, folds["test"])? != eligible
    {
        return Err(Error::new("Hero has inconsistent fold cohort counts"));
    }
    Ok((eligible, selection, folds))
}

fn parse_path_items(
    value: &Value,
    eligible: u64,
    selection: u64,
    folds: &BTreeMap<String, u64>,
) -> Result<Vec<ItemEvidence>> {
    let items = array(value)?
        .iter()
        .map(ItemEvidence::from_document)
        .collect::<Result<Vec<_>>>()?;
    let mut identities = BTreeSet::new();
    for item in &items {
        let item = item.content();
        if !identities.insert(item.item_id) {
            return Err(Error::new("Hero has duplicate item evidence"));
        }
        if item.eligible_player_matches != eligible
            || item.selection_eligible_player_matches != selection
            || item.training_eligible_player_matches != folds["train"]
            || item.validation_eligible_player_matches != folds["validation"]
            || item.test_eligible_player_matches != folds["test"]
        {
            return Err(Error::new(
                "Hero item denominators disagree with its cohort",
            ));
        }
    }
    Ok(items)
}

fn validate_policy_references(
    core: &CorePolicyEvidence,
    sequence: &SequencePolicy,
    situations: &SituationalPolicy,
    items: &[ItemEvidence],
) -> Result<()> {
    let by_id = items
        .iter()
        .map(|item| (item.content().item_id, item.content()))
        .collect::<BTreeMap<_, _>>();
    let sequence = sequence.content();
    let references = sequence.default_path.iter().copied().chain(
        sequence
            .transitions
            .iter()
            .map(|transition| transition.next_item_id),
    );
    if references.into_iter().any(|id| !by_id.contains_key(&id)) {
        return Err(Error::new(
            "Sequence policy references missing item evidence",
        ));
    }
    for branch in situations.branches() {
        let branch = branch.content();
        let item = by_id
            .get(&branch.item_id)
            .ok_or_else(|| Error::new("Situational item has no evidence"))?;
        let comparator = by_id
            .get(&branch.comparator_item_id)
            .ok_or_else(|| Error::new("Situational comparator has no evidence"))?;
        if item.adopter_matches < 20 {
            return Err(Error::new("Hero has an unsupported situational tier item"));
        }
        if !core
            .content()
            .default_item_ids
            .contains(&branch.comparator_item_id)
            || item.tier != u64::from(branch.tier)
            || comparator.tier != u64::from(branch.tier)
        {
            return Err(Error::new(
                "Hero has an invalid situational comparator or tier",
            ));
        }
    }
    Ok(())
}

fn validate_build_identities(builds: &[HeroBuildEvidence]) -> Result<()> {
    let mut paths = BTreeSet::new();
    let mut cores = BTreeSet::new();
    let mut ranks = BTreeSet::new();
    for build in builds {
        let mut core = build.core_policy.content().default_item_ids.clone();
        core.sort_unstable();
        let rank = integer(
            &build.discovery["selection_rank"],
            "frozen selection rank",
            0,
        )?;
        if !paths.insert(&build.path_id) || !cores.insert(core) || !ranks.insert(rank) {
            return Err(Error::new(
                "Hero has duplicate build paths, cores, or selection ranks",
            ));
        }
    }
    Ok(())
}
