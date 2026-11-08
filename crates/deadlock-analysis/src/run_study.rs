//! A run loaded for an experiment: its inputs, its folds, and the development item effects.
//!
//! Every experiment starts from the same three steps. This type holds them once, so the
//! experiments cannot split the folds or estimate the effects in different ways.

use std::cell::OnceCell;
use std::collections::BTreeSet;

use deadlock_data::{Error, Result};

use crate::build_assembly::{PHASES, PurchaseMedians};
use crate::item_effects::{EffectTable, ItemCatalog, LandmarkState, estimate_item_effects};
use crate::refresh_configuration::{ExtractionResources, RunPaths};
use crate::run_inputs::{AssemblyInputs, load_run_inputs};

#[derive(Debug)]
pub struct RunStudy {
    inputs: AssemblyInputs,
    development_effects: OnceCell<EffectTable>,
    all_effects: OnceCell<EffectTable>,
}

impl RunStudy {
    /// Loads the landmark states, the item catalog, and the purchase medians of a run.
    ///
    /// # Errors
    /// Returns an error when the manifest, the analysis database, or a query fails.
    pub fn load(paths: &RunPaths, resources: ExtractionResources) -> Result<Self> {
        Ok(Self {
            inputs: load_run_inputs(paths, resources)?,
            development_effects: OnceCell::new(),
            all_effects: OnceCell::new(),
        })
    }

    /// The heroes with landmark states in the run.
    #[must_use]
    pub fn hero_ids(&self) -> BTreeSet<u64> {
        self.inputs
            .states
            .iter()
            .map(|state| state.hero_id)
            .collect()
    }

    /// The item effects estimated from all folds, as production estimates them for the
    /// installed builds. The first call fits the models.
    ///
    /// # Errors
    /// Returns an error when a model cannot be fitted.
    pub fn all_effects(&self) -> Result<&EffectTable> {
        if self.all_effects.get().is_none() {
            eprintln!("Estimating item effects from all matches");
            let all = self.inputs.states.iter().collect::<Vec<_>>();
            let effects = estimate_item_effects(&all, self.catalog(), &PHASES)?;
            drop(self.all_effects.set(effects));
        }
        self.all_effects
            .get()
            .ok_or_else(|| Error::new("Item effects of all folds are missing"))
    }

    #[must_use]
    pub const fn catalog(&self) -> &ItemCatalog {
        &self.inputs.catalog
    }

    #[must_use]
    pub const fn medians(&self) -> &PurchaseMedians {
        &self.inputs.medians
    }

    /// All landmark states of the run, in database order.
    #[must_use]
    pub fn states(&self) -> &[LandmarkState] {
        &self.inputs.states
    }

    /// The held-out test states and the development states.
    #[must_use]
    pub fn folds(&self) -> (Vec<&LandmarkState>, Vec<&LandmarkState>) {
        self.inputs.states.iter().partition(|state| state.is_test())
    }

    /// The held-out test states.
    #[must_use]
    pub fn test(&self) -> Vec<&LandmarkState> {
        self.folds().0
    }

    /// The development states: every state outside the test fold.
    #[must_use]
    pub fn development(&self) -> Vec<&LandmarkState> {
        self.folds().1
    }

    /// The item effects estimated from the development states, as production estimates them
    /// for the held-out test. The first call fits the models.
    ///
    /// # Errors
    /// Returns an error when a model cannot be fitted.
    pub fn development_effects(&self) -> Result<&EffectTable> {
        if self.development_effects.get().is_none() {
            eprintln!("Estimating item effects from development matches");
            let effects = estimate_item_effects(&self.development(), self.catalog(), &PHASES)?;
            // A failed set means another caller filled the cell first with the same value.
            drop(self.development_effects.set(effects));
        }
        self.development_effects
            .get()
            .ok_or_else(|| Error::new("Development item effects are missing"))
    }

    /// The heroes with held-out test states.
    #[must_use]
    pub fn test_hero_ids(&self) -> BTreeSet<u64> {
        self.inputs
            .states
            .iter()
            .filter(|state| state.is_test())
            .map(|state| state.hero_id)
            .collect()
    }
}
