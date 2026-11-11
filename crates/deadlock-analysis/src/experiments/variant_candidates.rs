use deadlock_data::Result;

use crate::build_variants::{
    VariantCandidate, VariantGate, VariantSelection, explain_item_variants,
};
use crate::hero_assembly::{AssemblyContext, HeroAssembly};
use crate::item_effects::ItemAsset;
use crate::refresh_configuration::{ExtractionResources, RunPaths};
use crate::run_study::RunStudy;

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
/// The development gates repeat the selection of production. The production gates come from
/// the same hero assembly that production installs.
///
/// # Errors
/// Returns an error when the run, the analysis database, or a model fails.
pub fn explain_variant_candidates(
    paths: &RunPaths,
    resources: ExtractionResources,
    rule: VariantSelection,
) -> Result<Vec<VariantCandidateReport>> {
    let study = RunStudy::load(paths, resources)?;
    let catalog = study.catalog();
    let context = AssemblyContext {
        effects: study.all_effects()?,
        development_effects: study.development_effects()?,
        catalog,
        medians: study.medians(),
        selection: rule,
    };
    let mut reports = Vec::new();
    for hero_id in study.hero_ids() {
        let states = study
            .states()
            .iter()
            .filter(|state| state.hero_id == hero_id)
            .collect::<Vec<_>>();
        let assembly = HeroAssembly::assemble(hero_id, &states, &context)?;
        let Some(development_main) = &assembly.development_main else {
            continue;
        };
        let development = states
            .iter()
            .copied()
            .filter(|state| !state.is_test())
            .collect::<Vec<_>>();
        let candidates = explain_item_variants(
            hero_id,
            &development,
            context.development_effects,
            catalog,
            context.medians,
            development_main,
            rule,
        )?;
        for candidate in candidates {
            let production = (candidate.gate == VariantGate::Selected).then(|| {
                assembly
                    .dropped
                    .iter()
                    .find(|(item_id, _)| *item_id == candidate.item_id)
                    .map_or(VariantGate::Selected, |(_, gate)| *gate)
            });
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
