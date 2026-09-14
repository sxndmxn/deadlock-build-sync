use std::collections::BTreeSet;

use deadlock_data::Result;
use serde_json::{Value, json};

use crate::build_support::OutcomeEvidence;
use crate::hero_evidence::HeroEvidence;

pub fn filter_hero_builds(hero: &mut HeroEvidence) -> Result<Vec<Value>> {
    let mut records = Vec::new();
    let mut rejected_reasons = BTreeSet::new();
    for build in std::mem::take(&mut hero.builds) {
        let outcome = OutcomeEvidence::from_document(&build.discovery["validation"])?;
        let reasons = outcome.build_admission_rejections();
        records.push(json!({
            "hero_id":hero.hero_id,"hero":hero.hero,"path_id":build.path_id,
            "admitted":reasons.is_empty(),"rejection_reasons":reasons,
            "validation_win_rate":outcome.win_rate,"hero_validation_win_rate":outcome.hero_win_rate,
            "adjusted_difference":outcome.adjusted_difference,
            "comparable_core_owners":outcome.overlap,"comparable_core_share":outcome.overlap_share,
        }));
        if reasons.is_empty() {
            hero.builds.push(build);
        } else {
            rejected_reasons.extend(reasons);
        }
    }
    if hero.builds.is_empty() && hero.exclusion.is_none() {
        hero.exclusion = Some(format!(
            "No build meets validation admission requirements. {}",
            rejected_reasons.into_iter().collect::<Vec<_>>().join(". ")
        ));
    }
    Ok(records)
}
