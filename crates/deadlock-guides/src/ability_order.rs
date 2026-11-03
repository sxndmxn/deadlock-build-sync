use std::cmp::Reverse;
use std::collections::BTreeMap;

use deadlock_data::{ObservationCounts, Result};
use serde_json::Value;

/// A complete ability order and the matches that follow it to the end.
#[derive(Clone, Debug)]
pub struct AbilityPath {
    pub ability_ids: Vec<u64>,
    pub matches: u64,
}

#[derive(Clone, Debug, Default, Eq, Ord, PartialEq, PartialOrd)]
struct DecisionState {
    position: u8,
    ranks: BTreeMap<u64, u8>,
}

#[derive(Clone, Debug, Default)]
struct Continuation {
    path: Vec<u64>,
    matches: u64,
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
pub fn select_ability_path(rows: &[Value]) -> Result<Option<AbilityPath>> {
    let observations = rows
        .iter()
        .filter_map(parse_observation)
        .collect::<Vec<_>>();
    let decisions = aggregate_decisions(&observations)?;
    Ok(
        resolve_ability_continuation(&decisions, &DecisionState::default(), &mut BTreeMap::new())
            .map(|selected| AbilityPath {
                ability_ids: selected.path,
                matches: selected.matches,
            }),
    )
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

fn resolve_ability_continuation(
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
        if let Some(mut continuation) = resolve_ability_continuation(decisions, &next, cache) {
            if continuation.path.is_empty() {
                continuation.matches = counts.matches;
            }
            continuation.path.insert(0, *ability);
            return Some(continuation);
        }
    }
    None
}
