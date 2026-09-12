use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, EvidenceUnit, Result, SnapshotManifest};
use serde_json::{Map, Value};

use crate::ability_definition::AbilityDefinition;
use crate::guide_item::GuideItem;
use crate::policy_claim::{ClaimClass, EvidenceClaim};
use crate::purchase_guide::PurchaseGuide;
use crate::situational_branch::SituationalBranchContent;

pub struct ClaimContext<'manifest> {
    pub manifest: &'manifest SnapshotManifest,
    pub cohort: Map<String, Value>,
}

impl ClaimContext<'_> {
    pub fn claim(
        &self,
        id: String,
        class: ClaimClass,
        unit: EvidenceUnit,
        support: u64,
        language: &[&str],
    ) -> EvidenceClaim {
        EvidenceClaim {
            claim_id: id,
            claim_class: class,
            snapshot_id: self.manifest.identifier().into(),
            cohort: self.cohort.clone(),
            unit,
            support,
            mechanics_refs: Vec::new(),
            language_ceiling: language
                .iter()
                .map(|word| (*word).to_owned())
                .collect::<BTreeSet<_>>(),
            numerator: None,
            denominator: None,
            estimate: None,
            interval: None,
            comparison_baseline: None,
        }
    }

    fn item_claim(&self, item: &GuideItem) -> EvidenceClaim {
        let mut claim = self.claim(
            format!("item/{}/adoption", item.item_id),
            ClaimClass::Descriptive,
            EvidenceUnit::EligibleAppearance,
            item.eligible_player_matches,
            &["observed", "adopted", "rate", "more common"],
        );
        claim.mechanics_refs = vec![format!("item/{}", item.item_id)];
        claim.numerator = Some(item.adopter_matches);
        claim.denominator = Some(item.eligible_player_matches);
        claim.estimate = Some(item.purchase_adoption);
        claim
    }

    pub fn core_claim(&self, guide: &PurchaseGuide) -> Result<EvidenceClaim> {
        let support = guide
            .core_items
            .first()
            .ok_or_else(|| Error::new("Core policy requires at least one item"))?
            .eligible_player_matches;
        let mut claim = self.claim(
            format!("hero/{}/stable-supported-backbone", guide.hero_id),
            ClaimClass::Descriptive,
            EvidenceUnit::EligibleAppearance,
            support,
            &["observed", "adopted", "rate", "more common"],
        );
        claim.mechanics_refs = guide
            .backbone_items
            .iter()
            .map(|item| format!("item/{}", item.item_id))
            .collect();
        claim.numerator = Some(guide.backbone_matches);
        claim.denominator = Some(support);
        claim.estimate = Some(guide.backbone_share);
        Ok(claim)
    }

    pub fn situational_claim(
        &self,
        hero_id: u64,
        branch: &SituationalBranchContent,
    ) -> EvidenceClaim {
        let enemy = branch
            .enemy_hero_id
            .map_or_else(|| "any".into(), |id| id.to_string());
        let mut claim = self.claim(
            format!(
                "hero/{hero_id}/situational/{}/{enemy}/{}",
                branch.threat.as_str(),
                branch.item_id
            ),
            ClaimClass::Descriptive,
            EvidenceUnit::HeroEnemyPair,
            branch.support,
            &["observed", "associated"],
        );
        claim.mechanics_refs = vec![branch.mechanic_ref.clone()];
        claim.estimate =
            Some(branch.comparative_interval[0].midpoint(branch.comparative_interval[1]));
        claim.interval = Some(branch.comparative_interval);
        claim.comparison_baseline = Some(0.0);
        claim
    }

    pub fn base_evidence(
        &self,
        guide: &PurchaseGuide,
        definitions: &BTreeMap<u64, AbilityDefinition>,
    ) -> Result<BTreeMap<String, EvidenceClaim>> {
        let mut evidence = guide
            .tiers
            .values()
            .flatten()
            .chain(&guide.optional_core_items)
            .map(|item| self.item_claim(item))
            .map(|claim| (claim.claim_id.clone(), claim))
            .collect::<BTreeMap<_, _>>();
        let core = self.core_claim(guide)?;
        evidence.insert(core.claim_id.clone(), core);
        for id in definitions.keys() {
            let mut claim = self.claim(
                format!("ability/{id}/mechanics"),
                ClaimClass::Mechanical,
                EvidenceUnit::Asset,
                1,
                &["grants", "requires", "can target"],
            );
            claim.mechanics_refs.push(format!("ability/{id}"));
            evidence.insert(claim.claim_id.clone(), claim);
        }
        Ok(evidence)
    }
}
