//! The builds of one hero: the main build, the additional builds, and the dropped candidates.
//!
//! Production and the experiments call this one function, so an experiment cannot test a
//! selection that production does not make.

use deadlock_data::{Error, Result};

use crate::build_assembly::{
    AssembledBuild, PurchaseMedians, assemble_build, assemble_fallback_build,
};
use crate::build_variants::{
    VariantGate, VariantSelection, assemble_item_variant, select_item_variants_with_rule,
};
use crate::item_effects::{EffectTable, ItemCatalog, LandmarkState};

/// The effects and the rules that every hero assembly of a run shares.
#[derive(Clone, Copy, Debug)]
pub struct AssemblyContext<'a> {
    /// The item effects of all folds, for the installed builds.
    pub effects: &'a EffectTable,
    /// The item effects of the development fold, for the selection and the held-out test.
    pub development_effects: &'a EffectTable,
    pub catalog: &'a ItemCatalog,
    pub medians: &'a PurchaseMedians,
    pub selection: VariantSelection,
}

/// One additional build of a hero.
#[derive(Debug)]
pub struct HeroVariant {
    /// The installed build, from all folds.
    pub build: AssembledBuild,
    /// The build that the selector chose from the development fold. The held-out test uses it.
    pub development_build: AssembledBuild,
    /// The distinct player matches that own the key item, from all folds.
    pub owners: usize,
}

/// The assembled builds of one hero.
#[derive(Debug)]
pub struct HeroAssembly {
    pub main: AssembledBuild,
    /// The main build from the development fold, when the hero has development effects.
    pub development_main: Option<AssembledBuild>,
    /// True when the hero has no item effects of its own and the main build is generic.
    pub generic: bool,
    pub variants: Vec<HeroVariant>,
    /// Key items that the development selection chose and that production dropped.
    pub dropped: Vec<(u64, VariantGate)>,
}

impl HeroAssembly {
    /// Assembles the builds of a hero from its landmark states.
    ///
    /// The main build uses all folds. A hero without its own item effects gets the generic
    /// build of all heroes. The selector chooses additional builds from the development fold,
    /// and production re-assembles each one from all folds and checks that it is distinct.
    ///
    /// # Errors
    /// Returns an error when the run has no item effects at all, or when assembly fails.
    pub fn assemble(
        hero_id: u64,
        states: &[&LandmarkState],
        context: &AssemblyContext<'_>,
    ) -> Result<Self> {
        let AssemblyContext {
            effects,
            development_effects,
            catalog,
            medians,
            selection,
        } = *context;
        let (main, generic) = match assemble_build(hero_id, effects, catalog, medians) {
            Some(main) => (main, false),
            None => (
                assemble_fallback_build(hero_id, effects, catalog, medians)
                    .ok_or_else(|| Error::new("The run has no item effects"))?,
                true,
            ),
        };
        let development_main = assemble_build(hero_id, development_effects, catalog, medians);
        let mut assembly = Self {
            main,
            development_main,
            generic,
            variants: Vec::new(),
            dropped: Vec::new(),
        };
        let Some(development_main) = &assembly.development_main else {
            return Ok(assembly);
        };
        let development = states
            .iter()
            .copied()
            .filter(|state| !state.is_test())
            .collect::<Vec<_>>();
        let selected = select_item_variants_with_rule(
            hero_id,
            &development,
            development_effects,
            catalog,
            medians,
            development_main,
            selection,
        )?;
        for variant in selected {
            let item_id = variant.build.key_item_id;
            let Some(production) =
                assemble_item_variant(hero_id, item_id, states, effects, catalog, medians)?
            else {
                assembly.dropped.push((item_id, VariantGate::NoBuild));
                continue;
            };
            if assembly
                .installed()
                .any(|build| !selection.is_distinct(build, &production.build, catalog))
            {
                assembly.dropped.push((item_id, VariantGate::Similar));
                continue;
            }
            assembly.variants.push(HeroVariant {
                build: production.build,
                development_build: variant.build,
                owners: production.owners,
            });
        }
        Ok(assembly)
    }

    /// The main build and the additional builds, in installation order.
    pub fn installed(&self) -> impl Iterator<Item = &AssembledBuild> {
        std::iter::once(&self.main).chain(self.variants.iter().map(|variant| &variant.build))
    }
}
