use std::cmp::Reverse;
use std::collections::BTreeMap;

use deadlock_data::{ObservationCounts, Result};
use serde_json::Value;

use crate::ability_path::AbilityPath;

#[derive(Clone, Debug, Default, Eq, Ord, PartialEq, PartialOrd)]
struct DecisionState {
    position: u8,
    ranks: BTreeMap<u64, u8>,
}

#[derive(Clone, Debug, Default)]
struct Continuation {
    path: Vec<u64>,
    support: Vec<u64>,
    tail: ObservationCounts,
}

#[derive(Debug)]
struct Observation {
    path: Vec<u64>,
    counts: ObservationCounts,
}

type Decisions = BTreeMap<DecisionState, BTreeMap<u64, ObservationCounts>>;
type Continuations = BTreeMap<DecisionState, Option<Continuation>>;

/// Selects a complete ability order from the most supported legal decision states.
///
/// # Errors
/// Returns an error when combined observation counts exceed 64 bits.
pub fn select_ability_path(rows: &[Value], filter_item_ids: &[u64]) -> Result<Option<AbilityPath>> {
    let observations = rows
        .iter()
        .filter_map(parse_observation)
        .collect::<Vec<_>>();
    let cohort = sum_observations(observations.iter())?;
    if cohort.matches == 0 {
        return Ok(None);
    }
    let complete = sum_observations(
        observations
            .iter()
            .filter(|observation| observation.path.len() == 16),
    )?;
    let decisions = aggregate_decisions(&observations)?;
    let Some(selected) = compose(&decisions, &DecisionState::default(), &mut BTreeMap::new())
    else {
        return Ok(None);
    };
    let selection = if filter_item_ids.is_empty() {
        "MOST_SUPPORTED_LEGAL_STATE"
    } else {
        "MOST_SUPPORTED_LEGAL_STATE_ITEM_FILTERED"
    };
    Ok(Some(AbilityPath {
        ability_ids: selected.path,
        matches: selected.tail.matches,
        wins: selected.tail.wins,
        losses: selected.tail.losses,
        cohort_matches: cohort.matches,
        complete_path_matches: complete.matches,
        decision_support: selected.support,
        selection: selection.into(),
        filter_item_ids: filter_item_ids.to_vec(),
        fallback_reason: None,
    }))
}

fn parse_observation(row: &Value) -> Option<Observation> {
    let values = row["abilities"].as_array()?;
    if values.is_empty() || values.len() > 16 {
        return None;
    }
    let path = values
        .iter()
        .map(Value::as_u64)
        .collect::<Option<Vec<_>>>()?;
    let mut ranks = BTreeMap::<u64, u8>::new();
    for ability in &path {
        *ranks.entry(*ability).or_default() += 1;
    }
    if ranks.len() > 4 || ranks.contains_key(&0) || ranks.values().any(|count| *count > 4) {
        return None;
    }
    let counts = ObservationCounts {
        matches: row["matches"].as_u64()?,
        wins: row["wins"].as_u64()?,
        losses: row["losses"].as_u64()?,
    }
    .validate()
    .ok()?;
    (counts.matches > 0).then_some(Observation { path, counts })
}

fn sum_observations<'observation>(
    mut observations: impl Iterator<Item = &'observation Observation>,
) -> Result<ObservationCounts> {
    observations.try_fold(ObservationCounts::default(), |total, observation| {
        total.checked_add(observation.counts)
    })
}

fn aggregate_decisions(observations: &[Observation]) -> Result<Decisions> {
    let mut decisions = Decisions::new();
    for observation in observations {
        let mut state = DecisionState::default();
        for ability in &observation.path {
            let counts = decisions
                .entry(state.clone())
                .or_default()
                .entry(*ability)
                .or_default();
            *counts = counts.checked_add(observation.counts)?;
            *state.ranks.entry(*ability).or_default() += 1;
            state.position += 1;
        }
    }
    Ok(decisions)
}

fn compose(
    decisions: &Decisions,
    state: &DecisionState,
    cache: &mut Continuations,
) -> Option<Continuation> {
    if let Some(continuation) = cache.get(state) {
        return continuation.clone();
    }
    let result = select_continuation(decisions, state, cache);
    cache.insert(state.clone(), result.clone());
    result
}

fn select_continuation(
    decisions: &Decisions,
    state: &DecisionState,
    cache: &mut Continuations,
) -> Option<Continuation> {
    if state.position == 16 {
        return (state.ranks.len() == 4 && state.ranks.values().all(|count| *count == 4))
            .then(Continuation::default);
    }
    let mut candidates = decisions
        .get(state)?
        .iter()
        .filter(|(ability, _)| state.ranks.get(ability).copied().unwrap_or(0) < 4)
        .collect::<Vec<_>>();
    candidates.sort_by_key(|(ability, counts)| (Reverse(counts.matches), **ability));
    for (ability, counts) in candidates {
        let mut next = state.clone();
        next.position += 1;
        *next.ranks.entry(*ability).or_default() += 1;
        if let Some(mut continuation) = compose(decisions, &next, cache) {
            if continuation.path.is_empty() {
                continuation.tail = *counts;
            }
            continuation.path.insert(0, *ability);
            continuation.support.insert(0, counts.matches);
            return Some(continuation);
        }
    }
    None
}
