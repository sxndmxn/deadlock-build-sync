use std::collections::BTreeMap;

use deadlock_data::{Error, ObservationCounts, Result, count_ratio, round_decimal};
use deadlock_input::HeroDurationStat;
use serde::Serialize;
use serde_json::{Value, json};

const LABELS: [&str; 7] = [
    "<25m", "25–30m", "30–35m", "35–40m", "40–45m", "45–50m", "50m+",
];

#[derive(Clone, Debug, Serialize)]
pub struct DurationPopulation {
    pub hero_slots: u64,
    pub approximate_games: u64,
    pub tracked_game_share: f64,
}

pub type DurationDistribution = BTreeMap<String, DurationPopulation>;

#[derive(Debug)]
struct DurationPhase {
    label: &'static str,
    counts: ObservationCounts,
    rate: f64,
}

/// # Errors
/// Returns an error when combined observation counts exceed 64 bits or cannot form finite statistics.
pub fn summarize_duration_distribution(
    curves: &BTreeMap<u64, Vec<HeroDurationStat>>,
) -> Result<DurationDistribution> {
    distribution_from_points(curves.values().flatten())
}

fn distribution_from_points<'point>(
    points: impl Iterator<Item = &'point HeroDurationStat>,
) -> Result<DurationDistribution> {
    let mut slots = BTreeMap::<String, u64>::new();
    let mut total = 0_u64;
    for point in points {
        let count = slots.entry(point.label.clone()).or_default();
        let matches = u64::from(point.matches);
        *count = count
            .checked_add(matches)
            .ok_or_else(|| Error::new("Duration bucket population exceeds 64 bits"))?;
        total = total
            .checked_add(matches)
            .ok_or_else(|| Error::new("Duration population exceeds 64 bits"))?;
    }
    if total == 0 {
        return Ok(BTreeMap::new());
    }
    slots
        .into_iter()
        .map(|(label, hero_slots)| {
            let games = hero_slots / 12;
            let remainder = hero_slots % 12;
            let approximate_games =
                games + u64::from(remainder > 6 || (remainder == 6 && games % 2 != 0));
            Ok((
                label,
                DurationPopulation {
                    hero_slots,
                    approximate_games,
                    tracked_game_share: round_decimal(count_ratio(hero_slots, total)?, 6)?,
                },
            ))
        })
        .collect()
}

/// # Errors
/// Returns an error when the supplied observations cannot form finite duration statistics.
pub fn summarize_ending_duration_profile(
    points: &[HeroDurationStat],
    distribution: Option<&DurationDistribution>,
) -> Result<Option<Value>> {
    let Some(ordered) = ordered_points(points) else {
        return Ok(None);
    };
    let phases = [
        phase("EARLY (<30m)", &ordered[..2])?,
        phase("MID (30–45m)", &ordered[2..5])?,
        phase("LATE (45m+)", &ordered[5..])?,
    ];
    if phases.iter().any(|phase| phase.counts.matches < 50) {
        return Ok(None);
    }
    let fallback;
    let distribution = if let Some(distribution) = distribution.filter(|value| !value.is_empty()) {
        distribution
    } else {
        fallback = distribution_from_points(ordered.iter().copied())?;
        &fallback
    };
    let (strongest_phase, weakest_phase) = phase_extrema(&phases);
    let (strongest_bucket, weakest_bucket) = bucket_extrema(&ordered, distribution)?;
    let overall = phase("OVERALL", &ordered)?;
    let late_share = ordered[5..]
        .iter()
        .map(|point| share(distribution, &point.label))
        .sum();
    Ok(Some(json!({
        "estimand":"ending_duration_profile",
        "shape":profile_shape(&phases),
        "strongest_phase":phases[strongest_phase].label,
        "weakest_phase":phases[weakest_phase].label,
        "early_to_late_delta_percentage_points":round_decimal(100.0 * (phases[2].rate - phases[0].rate),2)?,
        "strongest_bucket":strongest_bucket.label,
        "weakest_bucket":weakest_bucket.label,
        "overall":{"raw_win_rate":round_decimal(overall.rate,6)?,"matches":overall.counts.matches},
        "late_phase_tracked_game_share":round_decimal(late_share,6)?,
        "fifty_plus_tracked_game_share":round_decimal(share(distribution,LABELS[6]),6)?,
        "phases":phases.iter().map(|phase| Ok(json!({"label":phase.label,"raw_win_rate":round_decimal(phase.rate,6)?,"matches":phase.counts.matches}))).collect::<Result<Vec<_>>>()?,
        "buckets":ordered.iter().map(|point| bucket_document(point,distribution)).collect::<Result<Vec<_>>>()?,
        "interpretation":"Duration buckets describe outcomes for matches with those ending durations. The rare 50m+ group cannot determine the profile alone. Use weighted phases and adjacent buckets. These observations do not establish that match duration or an item causes a result.",
    })))
}

fn ordered_points(points: &[HeroDurationStat]) -> Option<Vec<&HeroDurationStat>> {
    if points.len() != LABELS.len() {
        return None;
    }
    LABELS
        .iter()
        .map(|label| points.iter().find(|point| point.label == *label))
        .collect()
}

fn phase(label: &'static str, points: &[&HeroDurationStat]) -> Result<DurationPhase> {
    let mut counts = ObservationCounts::default();
    for point in points {
        let point = ObservationCounts {
            matches: u64::from(point.matches),
            wins: u64::from(point.wins),
            losses: u64::from(point.losses),
        }
        .validate()?;
        counts = counts.checked_add(point)?;
    }
    Ok(DurationPhase {
        label,
        counts,
        rate: counts.win_rate()?,
    })
}

fn phase_extrema(phases: &[DurationPhase; 3]) -> (usize, usize) {
    let mut strongest = 0;
    let mut weakest = 0;
    for index in 1..phases.len() {
        if phases[index].rate > phases[strongest].rate {
            strongest = index;
        }
        if phases[index].rate < phases[weakest].rate {
            weakest = index;
        }
    }
    (strongest, weakest)
}

fn profile_shape(phases: &[DurationPhase; 3]) -> &'static str {
    let (strongest, weakest) = phase_extrema(phases);
    let [early, middle, late] = phases.each_ref().map(|phase| phase.rate);
    if phases[strongest].rate - phases[weakest].rate < 0.015 {
        "STABLE"
    } else if middle >= early + 0.01 && middle >= late + 0.01 {
        "MIDGAME_PEAK"
    } else if late >= early + 0.02 {
        "LATE_SCALING"
    } else if early >= late + 0.02 {
        "EARLY_CLOSER"
    } else {
        "MIXED"
    }
}

fn bucket_extrema<'point>(
    points: &[&'point HeroDurationStat],
    distribution: &DurationDistribution,
) -> Result<(&'point HeroDurationStat, &'point HeroDurationStat)> {
    let representative = points
        .iter()
        .copied()
        .filter(|point| share(distribution, &point.label) >= 0.03)
        .collect::<Vec<_>>();
    let selected = if representative.is_empty() {
        points
    } else {
        &representative
    };
    let mut strongest = *selected
        .first()
        .ok_or_else(|| Error::new("Duration profile has no buckets"))?;
    let mut weakest = strongest;
    for point in selected {
        if point.win_rate() > strongest.win_rate() {
            strongest = point;
        }
        if point.win_rate() < weakest.win_rate() {
            weakest = point;
        }
    }
    Ok((strongest, weakest))
}

fn share(distribution: &DurationDistribution, label: &str) -> f64 {
    distribution
        .get(label)
        .map_or(0.0, |population| population.tracked_game_share)
}

fn bucket_document(point: &HeroDurationStat, distribution: &DurationDistribution) -> Result<Value> {
    let population = distribution
        .get(&point.label)
        .map(serde_json::to_value)
        .transpose()?
        .unwrap_or_else(|| json!({}));
    Ok(
        json!({"label":point.label,"min_duration_s":point.min_duration_s,"max_duration_s":point.max_duration_s,"raw_win_rate":round_decimal(point.win_rate(),6)?,"matches":point.matches,"population":population}),
    )
}
