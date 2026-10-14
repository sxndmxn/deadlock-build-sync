#![forbid(unsafe_code)]

//! Compares item effect model designs by held-out log loss on one extracted run.
//!
//! Usage: `cargo run --release --example compare_effect_models -- RUN_DIRECTORY [GLOBAL:HERO[:lead=SCALE|:spirit=SCALE] ...]`
//!
//! `GLOBAL` and `HERO` are the item ridge penalties. `lead=SCALE` adds item and team lead
//! interactions. `spirit=SCALE` adds item and enemy spirit share interactions.
//! The output is tab-separated text with one line for each design.
//! A lower log loss means better predictions of match results.

use std::path::Path;

use deadlock_analysis::{
    DEFAULT_PENALTIES, EffectModel, EffectPenalties, ExtractionResources, Interaction, RunPaths,
    compare_effect_models,
};
use deadlock_data::{Error, Result};

const USAGE: &str =
    "Usage: compare_effect_models RUN_DIRECTORY [GLOBAL:HERO[:lead=SCALE|:spirit=SCALE] ...]";
const GLOBAL_PENALTIES: [f64; 5] = [1.0, 5.0, 20.0, 50.0, 200.0];
const HERO_PENALTIES: [f64; 4] = [20.0, 100.0, 300.0, 1000.0];
/// Penalties large enough to remove all item effects. This design is the baseline.
const BASELINE: EffectPenalties = EffectPenalties {
    global_item: 1e9,
    hero_item: 1e9,
};

fn main() -> Result<()> {
    let mut arguments = std::env::args().skip(1);
    let run = arguments.next().ok_or_else(|| Error::new(USAGE))?;
    let paths = RunPaths::open(Path::new(&run))?;
    let mut designs = arguments
        .map(|value| parse_design(&value))
        .collect::<Result<Vec<_>>>()?;
    if designs.is_empty() {
        designs.push(EffectModel {
            penalties: BASELINE,
            interaction: None,
        });
        for global_item in GLOBAL_PENALTIES {
            for hero_item in HERO_PENALTIES {
                designs.push(EffectModel {
                    penalties: EffectPenalties {
                        global_item,
                        hero_item,
                    },
                    interaction: None,
                });
            }
        }
    }
    let resources = ExtractionResources {
        memory_limit_mb: 12_000,
        threads: 8,
    };
    println!(
        "global_item\thero_item\tinteraction\tdefault\tlog_loss\tdifference_from_first\tstandard_error\tobservations"
    );
    for result in compare_effect_models(&paths, resources, &designs)? {
        let penalties = result.model.penalties;
        let default = result.model.interaction.is_none()
            && penalties
                .global_item
                .total_cmp(&DEFAULT_PENALTIES.global_item)
                .is_eq()
            && penalties
                .hero_item
                .total_cmp(&DEFAULT_PENALTIES.hero_item)
                .is_eq();
        println!(
            "{}\t{}\t{}\t{}\t{:.6}\t{:.6}\t{:.6}\t{}",
            penalties.global_item,
            penalties.hero_item,
            match result.model.interaction {
                None => "none".to_owned(),
                Some((Interaction::TeamLead, scale)) => format!("lead={scale}"),
                Some((Interaction::EnemySpirit, scale)) => format!("spirit={scale}"),
            },
            if default { "yes" } else { "no" },
            result.log_loss,
            result.difference,
            result.difference_standard_error,
            result.observations
        );
    }
    Ok(())
}

fn parse_design(value: &str) -> Result<EffectModel> {
    let invalid = || {
        Error::new(format!(
            "Design must be GLOBAL:HERO[:lead=SCALE|:spirit=SCALE] with positive penalties and a scale of 0 or more: {value}"
        ))
    };
    let number = |text: &str| {
        text.parse::<f64>()
            .ok()
            .filter(|number| *number > 0.0)
            .ok_or_else(invalid)
    };
    let mut parts = value.split(':');
    let global_item = number(parts.next().ok_or_else(invalid)?)?;
    let hero_item = number(parts.next().ok_or_else(invalid)?)?;
    let interaction = match parts.next() {
        None => None,
        Some(text) => {
            let (name, scale) = text.split_once('=').ok_or_else(invalid)?;
            let kind = match name {
                "lead" => Interaction::TeamLead,
                "spirit" => Interaction::EnemySpirit,
                _ => return Err(invalid()),
            };
            let scale = scale
                .parse::<f64>()
                .ok()
                .filter(|scale| *scale >= 0.0)
                .ok_or_else(invalid)?;
            Some((kind, scale))
        }
    };
    if parts.next().is_some() {
        return Err(invalid());
    }
    Ok(EffectModel {
        penalties: EffectPenalties {
            global_item,
            hero_item,
        },
        interaction,
    })
}
