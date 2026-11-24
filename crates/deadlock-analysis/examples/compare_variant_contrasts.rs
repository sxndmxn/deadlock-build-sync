#![forbid(unsafe_code)]

//! Tests each additional build against the main build of its hero on held-out matches (E39).
//!
//! Usage: `cargo run --release --example compare_variant_contrasts -- RUN_DIRECTORY DISTINCT_ITEMS SEPARATION REPETITIONS`
//!
//! The output is tab-separated text with one line for each additional build: the contrast on
//! all test matches and on the even and odd match halves. The lines that start with `#` give
//! the correlation of the halves, the variance between builds beyond the noise, and the
//! placebo z values.

use std::path::Path;

use deadlock_analysis::{
    CoefficientEstimate, ExtractionResources, RunPaths, VariantSelection, compare_variant_contrasts,
};
use deadlock_data::{Error, Result, count_as_f64};

const USAGE: &str =
    "Usage: compare_variant_contrasts RUN_DIRECTORY DISTINCT_ITEMS SEPARATION REPETITIONS";

fn main() -> Result<()> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    let [run, items, separation, repetitions] = arguments.as_slice() else {
        return Err(Error::new(USAGE));
    };
    let selection = VariantSelection {
        minimum_distinct_items: items.parse().map_err(|_| Error::new(USAGE))?,
        minimum_separation: separation.parse().map_err(|_| Error::new(USAGE))?,
        ..VariantSelection::default()
    };
    let repetitions = repetitions.parse::<u64>().map_err(|_| Error::new(USAGE))?;
    let seeds = (1..=repetitions).collect::<Vec<_>>();
    let paths = RunPaths::open(Path::new(run))?;
    let contrasts =
        compare_variant_contrasts(&paths, ExtractionResources::default(), selection, &seeds)?;
    println!(
        "hero_id\tkey_item_id\tobservations\tcontrast\tstandard_error\tz\teven\teven_error\todd\todd_error"
    );
    let format = |estimate: Option<CoefficientEstimate>| {
        estimate.map_or_else(
            || "\t".to_owned(),
            |value| format!("{:.4}\t{:.4}", value.coefficient, value.standard_error),
        )
    };
    let mut full = Vec::new();
    let mut halves = Vec::new();
    let mut placebo = Vec::new();
    for contrast in &contrasts {
        let [all, even, odd] = contrast.estimates;
        let z = all.map_or(f64::NAN, |value| value.coefficient / value.standard_error);
        println!(
            "{}\t{}\t{}\t{}\t{z:.2}\t{}\t{}",
            contrast.hero_id,
            contrast.key_item_id,
            contrast.observations,
            format(all),
            format(even),
            format(odd)
        );
        full.extend(all.map(|value| (value.coefficient, value.standard_error)));
        if let (Some(even), Some(odd)) = (even, odd) {
            halves.push((even.coefficient, odd.coefficient));
        }
        placebo.extend(&contrast.placebo_z);
    }
    let z_values = full
        .iter()
        .map(|(coefficient, error)| coefficient / error)
        .collect::<Vec<_>>();
    report("contrast z", &z_values)?;
    report("placebo z", &placebo)?;
    println!(
        "# halves: {} builds, correlation {:.3}",
        halves.len(),
        correlate(&halves)?
    );
    let (mean, between) = estimate_between_variance(&full)?;
    println!(
        "# contrasts: precision-weighted mean {mean:.4}, variance between builds beyond noise {between:.5}"
    );
    Ok(())
}

fn count(values: usize) -> Result<f64> {
    count_as_f64(u64::try_from(values)?)
}

fn report(name: &str, values: &[f64]) -> Result<()> {
    let count = count(values.len().max(1))?;
    let mean = values.iter().sum::<f64>() / count;
    let deviation = (values
        .iter()
        .map(|value| (value - mean).powi(2))
        .sum::<f64>()
        / count)
        .sqrt();
    let beyond = |limit: f64| values.iter().filter(|value| value.abs() > limit).count();
    let below = values.iter().filter(|value| **value < -2.0).count();
    println!(
        "# {name}: {} values, mean {mean:.3}, standard deviation {deviation:.3}, beyond ±2 {}, below −2 {below}, beyond ±3 {}",
        values.len(),
        beyond(2.0),
        beyond(3.0)
    );
    Ok(())
}

fn correlate(pairs: &[(f64, f64)]) -> Result<f64> {
    let count = count(pairs.len().max(1))?;
    let (first_mean, second_mean) = pairs.iter().fold((0.0, 0.0), |(first, second), (a, b)| {
        (first + a / count, second + b / count)
    });
    let covariance = pairs
        .iter()
        .map(|(a, b)| (a - first_mean) * (b - second_mean))
        .sum::<f64>();
    let first = pairs
        .iter()
        .map(|(a, _)| (a - first_mean).powi(2))
        .sum::<f64>();
    let second = pairs
        .iter()
        .map(|(_, b)| (b - second_mean).powi(2))
        .sum::<f64>();
    Ok(covariance / (first * second).sqrt().max(f64::MIN_POSITIVE))
}

/// Returns the precision-weighted mean and the variance between builds beyond their noise.
fn estimate_between_variance(estimates: &[(f64, f64)]) -> Result<(f64, f64)> {
    let count = count(estimates.len().max(2))?;
    let weights = estimates
        .iter()
        .map(|(_, error)| error.powi(-2))
        .sum::<f64>();
    let pooled = estimates
        .iter()
        .map(|(value, error)| value * error.powi(-2))
        .sum::<f64>()
        / weights;
    let mean = estimates.iter().map(|(value, _)| value).sum::<f64>() / count;
    let spread = estimates
        .iter()
        .map(|(value, _)| (value - mean).powi(2))
        .sum::<f64>()
        / (count - 1.0);
    let noise = estimates
        .iter()
        .map(|(_, error)| error.powi(2))
        .sum::<f64>()
        / count;
    Ok((pooled, (spread - noise).max(0.0)))
}
