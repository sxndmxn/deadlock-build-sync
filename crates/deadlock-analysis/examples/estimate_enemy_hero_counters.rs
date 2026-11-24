#![forbid(unsafe_code)]

//! Tests whether item groups win less or more against specific enemy heroes (E38).
//!
//! Usage: `cargo run --release --example estimate_enemy_hero_counters -- RUN_DIRECTORY HERO_IDS GROUP_CLASSES... [hero=ID] [parity=0|1] [placebo=REPETITIONS] [screen]`
//!
//! `HERO_IDS` is a comma-separated list of enemy hero identifiers. Its condition is the count of
//! these heroes in the enemy team, standardized within the phase. Each group is a
//! comma-separated list of item class names. `hero=ID` uses the states of one hero only.
//! `parity=0` or `parity=1` uses only the matches with an even or odd identifier.
//! `placebo=REPETITIONS` repeats the test after the enemy teams move to other teams at random.
//! `screen` ignores `HERO_IDS` and tests each enemy hero alone, on all matches and on the even
//! and odd match halves. The output is tab-separated text.

use std::collections::BTreeSet;
use std::path::Path;

use deadlock_analysis::{
    EnemyHeroResult, EnemyHeroStudy, EnemyHeroTest, ExtractionResources, RunPaths,
};
use deadlock_data::{Error, Result, count_as_f64};

const USAGE: &str = "Usage: estimate_enemy_hero_counters RUN_DIRECTORY HERO_IDS GROUP_CLASSES... [hero=ID] [parity=0|1] [placebo=REPETITIONS] [screen]";

fn main() -> Result<()> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    let [run, heroes, rest @ ..] = arguments.as_slice() else {
        return Err(Error::new(USAGE));
    };
    let mut hero_id = None;
    let mut match_parity = None;
    let mut repetitions = 0;
    let mut screen = false;
    let mut groups = Vec::new();
    for argument in rest {
        if let Some(value) = argument.strip_prefix("hero=") {
            hero_id = Some(value.parse::<u64>().map_err(|_| Error::new(USAGE))?);
        } else if let Some(value) = argument.strip_prefix("parity=") {
            match_parity = Some(value.parse::<u64>().map_err(|_| Error::new(USAGE))? % 2);
        } else if let Some(value) = argument.strip_prefix("placebo=") {
            repetitions = value.parse::<u64>().map_err(|_| Error::new(USAGE))?;
        } else if argument == "screen" {
            screen = true;
        } else {
            groups.push(argument.split(',').map(str::to_owned).collect::<Vec<_>>());
        }
    }
    if groups.is_empty() {
        return Err(Error::new(USAGE));
    }
    let paths = RunPaths::open(Path::new(run))?;
    let study = EnemyHeroStudy::load(&paths, ExtractionResources::default())?;
    let base = EnemyHeroTest {
        conditions: Vec::new(),
        standardize: !screen,
        groups,
        hero_id,
        match_parity,
        placebo_seed: None,
    };
    if screen {
        return run_screen(&study, base);
    }
    let selected = heroes
        .split(',')
        .map(|value| value.parse::<u64>().map_err(|_| Error::new(USAGE)))
        .collect::<Result<BTreeSet<_>>>()?;
    let test = EnemyHeroTest {
        conditions: vec![selected],
        ..base
    };
    println!("test\tphase_s\tgroup\tcoefficient\tstandard_error\tz\tobservations");
    print_results("real", &study.measure(&test)?, |_| 0);
    for seed in 1..=repetitions {
        let placebo = EnemyHeroTest {
            placebo_seed: Some(seed),
            ..test.clone()
        };
        print_results(&format!("placebo-{seed}"), &study.measure(&placebo)?, |_| 0);
    }
    Ok(())
}

/// Tests each enemy hero alone, on all matches and on each match half.
fn run_screen(study: &EnemyHeroStudy, base: EnemyHeroTest) -> Result<()> {
    let enemies = study.hero_ids().into_iter().collect::<Vec<_>>();
    let test = EnemyHeroTest {
        conditions: enemies.iter().map(|hero| BTreeSet::from([*hero])).collect(),
        ..base
    };
    println!("test\tphase_s\tenemy_hero_id\tgroup\tcoefficient\tstandard_error\tz\tobservations");
    let mut halves = Vec::new();
    for (name, parity) in [("all", None), ("even", Some(0)), ("odd", Some(1))] {
        let results = study.measure(&EnemyHeroTest {
            match_parity: parity,
            ..test.clone()
        })?;
        print_results(name, &results, |condition| enemies[condition]);
        halves.push(results);
    }
    let pairs = halves[1]
        .iter()
        .zip(&halves[2])
        .flat_map(|(even, odd)| {
            even.interactions
                .iter()
                .flatten()
                .zip(odd.interactions.iter().flatten())
                .map(|(first, second)| (first.coefficient, second.coefficient))
        })
        .collect::<Vec<_>>();
    println!(
        "# halves: {} pairs, correlation {:.3}",
        pairs.len(),
        correlate(&pairs)?
    );
    Ok(())
}

fn print_results(name: &str, results: &[EnemyHeroResult], enemy: impl Fn(usize) -> u64) {
    let screen = name == "all" || name == "even" || name == "odd";
    for result in results {
        for (condition, interactions) in result.interactions.iter().enumerate() {
            for (group, value) in interactions.iter().enumerate() {
                let prefix = if screen {
                    format!("{name}\t{}\t{}", result.phase_s, enemy(condition))
                } else {
                    format!("{name}\t{}", result.phase_s)
                };
                println!(
                    "{prefix}\t{group}\t{:.4}\t{:.4}\t{:.2}\t{}",
                    value.coefficient,
                    value.standard_error,
                    value.coefficient / value.standard_error,
                    result.observations
                );
            }
        }
    }
}

fn correlate(pairs: &[(f64, f64)]) -> Result<f64> {
    let count = count_as_f64(u64::try_from(pairs.len().max(1))?)?;
    let first_mean = pairs.iter().map(|(first, _)| first).sum::<f64>() / count;
    let second_mean = pairs.iter().map(|(_, second)| second).sum::<f64>() / count;
    let covariance = pairs
        .iter()
        .map(|(first, second)| (first - first_mean) * (second - second_mean))
        .sum::<f64>();
    let first = pairs
        .iter()
        .map(|(first, _)| (first - first_mean).powi(2))
        .sum::<f64>();
    let second = pairs
        .iter()
        .map(|(_, second)| (second - second_mean).powi(2))
        .sum::<f64>();
    Ok(covariance / (first * second).sqrt().max(f64::MIN_POSITIVE))
}
