use std::collections::BTreeMap;

use deadlock_data::{Error, ObservationCounts, Result, count_as_f64, count_ratio};
use serde::{Deserialize, Serialize};

pub const PURCHASE_BUCKET_INCREMENTS: [u64; 6] = [1000, 2000, 3000, 5000, 7000, 10_000];

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct PurchaseBucketRow {
    pub bucket: Option<u64>,
    pub matches: u64,
    pub wins: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PurchaseWindow {
    pub bucket_start: u64,
    pub bucket_end: u64,
    pub matches: u64,
    pub wins: u64,
    pub observed_outcome_rate: f64,
    pub wilson_lower_bound: f64,
}

pub type GroupedPurchaseBucket = PurchaseWindow;

/// # Errors
/// Returns an error for inconsistent counts, an invalid confidence parameter, or nonfinite statistics.
pub fn wilson_score_interval(wins: u64, matches: u64, z: f64) -> Result<(f64, f64)> {
    if wins > matches || !z.is_finite() || z < 0.0 {
        return Err(Error::new(
            "Wilson interval requires valid outcome counts and a finite nonnegative confidence parameter",
        ));
    }
    if matches == 0 {
        return Ok((0.0, 0.0));
    }
    let matches = count_as_f64(matches)?;
    let proportion = count_as_f64(wins)? / matches;
    let scaled_z = z * z / matches;
    let denominator = 1.0 + scaled_z;
    let center_correction = scaled_z * 0.5;
    let center = proportion + center_correction;
    let binomial_variance = proportion * (1.0 - proportion);
    let variance_correction = scaled_z * 0.25;
    let variance = (binomial_variance + variance_correction) / matches;
    let margin = z * variance.sqrt();
    let interval = (
        (center - margin) / denominator,
        (center + margin) / denominator,
    );
    if !interval.0.is_finite() || !interval.1.is_finite() {
        return Err(Error::new("Wilson interval is not finite"));
    }
    Ok(interval)
}

/// # Errors
/// Returns an error for a zero increment, inconsistent counts, or an integer overflow.
pub fn group_purchase_buckets(
    rows: &[PurchaseBucketRow],
    increment: u64,
) -> Result<Vec<GroupedPurchaseBucket>> {
    if increment == 0 {
        return Err(Error::new("Purchase bucket increment must be positive"));
    }
    let mut groups = BTreeMap::<u64, ObservationCounts>::new();
    for row in rows {
        let Some(bucket) = row.bucket else {
            continue;
        };
        if row.matches == 0 {
            continue;
        }
        let key = bucket / increment * increment;
        let counts = counts(row.matches, row.wins)?;
        let total = groups.entry(key).or_default();
        *total = total.checked_add(counts)?;
    }
    groups
        .into_iter()
        .map(|(start, counts)| {
            let end = start
                .checked_add(increment)
                .ok_or_else(|| Error::new("Purchase bucket boundary exceeds 64 bits"))?;
            window(start, end, counts)
        })
        .collect()
}

/// # Errors
/// Returns an error when bucket grouping or observation count conversion fails.
pub fn compute_average_bucket_matches(rows: &[PurchaseBucketRow], increment: u64) -> Result<f64> {
    let groups = group_purchase_buckets(rows, increment)?;
    let total = total_matches(groups.iter().map(|group| group.matches))?;
    count_ratio(total, u64::try_from(groups.len())?)
}

/// # Errors
/// Returns an error when an increment is zero or bucket statistics are invalid.
pub fn choose_adaptive_bucket_increment(
    rows: &[PurchaseBucketRow],
    total: u64,
    increments: &[u64],
) -> Result<u64> {
    let fallback = increments.last().copied().unwrap_or(1000);
    if total == 0 {
        return Ok(fallback);
    }
    let average_share = if total > 200 { 0.10 } else { 0.15 };
    for increment in increments {
        if compute_average_bucket_matches(rows, *increment)? / count_as_f64(total)? >= average_share
        {
            return Ok(*increment);
        }
    }
    Ok(fallback)
}

/// # Errors
/// Returns an error when purchase observations or horizon calculations exceed their numeric limits.
pub fn calculate_tier_horizons(
    series: &[(u8, Vec<PurchaseBucketRow>)],
) -> Result<BTreeMap<u8, u64>> {
    let mut tiers = BTreeMap::<u8, Vec<PurchaseBucketRow>>::new();
    for (tier, rows) in series {
        tiers.entry(*tier).or_default().extend_from_slice(rows);
    }
    let mut horizons = BTreeMap::new();
    for (tier, rows) in tiers {
        if let Some(median) = weighted_median(&rows)? {
            let doubled = median
                .checked_mul(2)
                .ok_or_else(|| Error::new("Purchase median exceeds the horizon range"))?;
            let horizon = doubled
                .div_ceil(1000)
                .checked_mul(1000)
                .ok_or_else(|| Error::new("Purchase horizon exceeds 64 bits"))?;
            horizons.insert(tier, horizon);
        }
    }
    Ok(horizons)
}

fn weighted_median(rows: &[PurchaseBucketRow]) -> Result<Option<u64>> {
    let mut rows = rows
        .iter()
        .filter(|row| row.bucket.is_some() && row.matches > 0)
        .collect::<Vec<_>>();
    rows.sort_by_key(|row| row.bucket);
    let total = total_matches(rows.iter().map(|row| row.matches))?;
    if total == 0 {
        return Ok(None);
    }
    let mut cumulative = 0;
    for row in rows {
        cumulative += row.matches;
        if cumulative >= total.div_ceil(2) {
            return row
                .bucket
                .map(|bucket| {
                    bucket
                        .checked_add(500)
                        .ok_or_else(|| Error::new("Purchase median exceeds 64 bits"))
                })
                .transpose();
        }
    }
    Ok(None)
}

/// Selects the central purchase-event range without using outcome peaks.
///
/// # Errors
/// Returns an error when the supplied buckets contain inconsistent or overflowing counts.
pub fn select_purchase_windows(
    groups: &[GroupedPurchaseBucket],
    horizon: u64,
    total_bucket_matches: Option<u64>,
) -> Result<Vec<PurchaseWindow>> {
    let total = total_bucket_matches.map_or_else(
        || total_matches(groups.iter().map(|group| group.matches)),
        Ok,
    )?;
    let minimum = 20.max(total.div_ceil(20));
    let eligible = groups
        .iter()
        .filter(|group| group.bucket_end <= horizon && group.matches >= minimum)
        .collect::<Vec<_>>();
    if eligible.is_empty() {
        return Ok(Vec::new());
    }
    let total = total_matches(eligible.iter().map(|group| group.matches))?;
    let start = quartile_index(&eligible, total, 1);
    let end = quartile_index(&eligible, total, 3);
    let selected = &eligible[start..=end];
    let total = selected
        .iter()
        .try_fold(ObservationCounts::default(), |total, group| {
            total.checked_add(counts(group.matches, group.wins)?)
        })?;
    Ok(vec![window(
        eligible[start].bucket_start,
        eligible[end].bucket_end,
        total,
    )?])
}

fn quartile_index(groups: &[&PurchaseWindow], total: u64, numerator: u8) -> usize {
    let target = (u128::from(total) * u128::from(numerator)).div_ceil(4);
    let mut cumulative = 0_u128;
    for (index, group) in groups.iter().enumerate() {
        cumulative += u128::from(group.matches);
        if cumulative >= target {
            return index;
        }
    }
    groups.len().saturating_sub(1)
}

/// # Errors
/// Returns an error when purchase observations or bucket boundaries are invalid.
pub fn analyze_purchase_windows(
    rows: &[PurchaseBucketRow],
    row_total_matches: u64,
    horizon: u64,
) -> Result<Vec<PurchaseWindow>> {
    let increment =
        choose_adaptive_bucket_increment(rows, row_total_matches, &PURCHASE_BUCKET_INCREMENTS)?;
    let groups = group_purchase_buckets(rows, increment)?;
    let total = total_matches(rows.iter().map(|row| row.matches))?;
    select_purchase_windows(&groups, horizon, Some(total))
}

fn counts(matches: u64, wins: u64) -> Result<ObservationCounts> {
    let losses = matches
        .checked_sub(wins)
        .ok_or_else(|| Error::new("Purchase wins exceed the observation count"))?;
    Ok(ObservationCounts {
        matches,
        wins,
        losses,
    })
}

fn window(start: u64, end: u64, counts: ObservationCounts) -> Result<PurchaseWindow> {
    Ok(PurchaseWindow {
        bucket_start: start,
        bucket_end: end,
        matches: counts.matches,
        wins: counts.wins,
        observed_outcome_rate: counts.win_rate()?,
        wilson_lower_bound: wilson_score_interval(counts.wins, counts.matches, 1.96)?.0,
    })
}

fn total_matches(mut matches: impl Iterator<Item = u64>) -> Result<u64> {
    matches.try_fold(0_u64, |total, count| {
        total
            .checked_add(count)
            .ok_or_else(|| Error::new("Purchase observation count exceeds 64 bits"))
    })
}
