use std::collections::BTreeSet;

use deadlock_data::Result;

use crate::build_assembly::{PHASES, assemble_build};
use crate::build_variants::{
    VariantCandidate, VariantGate, VariantSelection, describe_item_variant, explain_item_variants,
};
use crate::item_effects::{ItemAsset, estimate_item_effects};
use crate::refresh_configuration::{ExtractionResources, RunPaths};
use crate::run_inputs::load_run_inputs;

/// The gate results of one candidate key item in development and in production.
#[derive(Clone, Debug)]
pub struct VariantCandidateReport {
    pub hero_id: u64,
    pub item: ItemAsset,
    /// The gate result from development matches, as the selector sees it.
    pub development: VariantCandidate,
    /// The production gate of a selected candidate: the build from all folds can still fail.
    pub production: Option<VariantGate>,
}

/// Reports the gate result of every Tier 3 or Tier 4 item of every hero in a run.
///
/// The development gates repeat the selection of production. For each selected candidate,
/// the report also repeats the production assembly from all folds and its separation check.
///
/// # Errors
/// Returns an error when the run, the analysis database, or a model fails.
pub fn explain_variant_candidates(
    paths: &RunPaths,
    resources: ExtractionResources,
    rule: VariantSelection,
) -> Result<Vec<VariantCandidateReport>> {
    let inputs = load_run_inputs(paths, resources)?;
    let catalog = &inputs.catalog;
    let all = inputs.states.iter().collect::<Vec<_>>();
    let development = all
        .iter()
        .copied()
        .filter(|state| !state.is_test())
        .collect::<Vec<_>>();
    eprintln!("Estimating item effects from development matches");
    let development_effects = estimate_item_effects(&development, catalog, &PHASES)?;
    eprintln!("Estimating item effects from all matches");
    let effects = estimate_item_effects(&all, catalog, &PHASES)?;
    let hero_ids = all
        .iter()
        .map(|state| state.hero_id)
        .collect::<BTreeSet<_>>();
    let mut reports = Vec::new();
    for hero_id in hero_ids {
        let Some(development_main) =
            assemble_build(hero_id, &development_effects, catalog, &inputs.medians)
        else {
            continue;
        };
        let hero_development = development
            .iter()
            .copied()
            .filter(|state| state.hero_id == hero_id)
            .collect::<Vec<_>>();
        let candidates = explain_item_variants(
            hero_id,
            &hero_development,
            &development_effects,
            catalog,
            &inputs.medians,
            &development_main,
            rule,
        )?;
        let hero_all = all
            .iter()
            .copied()
            .filter(|state| state.hero_id == hero_id)
            .collect::<Vec<_>>();
        let mut installed = assemble_build(hero_id, &effects, catalog, &inputs.medians)
            .into_iter()
            .collect::<Vec<_>>();
        for candidate in candidates {
            let production = if candidate.gate == VariantGate::Selected {
                let (gate, variant) = describe_item_variant(
                    hero_id,
                    candidate.item_id,
                    &hero_all,
                    &effects,
                    catalog,
                    &inputs.medians,
                )?;
                Some(match variant {
                    None => gate.gate,
                    Some(variant)
                        if installed
                            .iter()
                            .any(|build| !rule.is_distinct(build, &variant.build, catalog)) =>
                    {
                        VariantGate::Similar
                    }
                    Some(variant) => {
                        installed.push(variant.build);
                        VariantGate::Selected
                    }
                })
            } else {
                None
            };
            let Some(item) = catalog.asset(candidate.item_id) else {
                continue;
            };
            reports.push(VariantCandidateReport {
                hero_id,
                item: item.clone(),
                development: candidate,
                production,
            });
        }
    }
    Ok(reports)
}
