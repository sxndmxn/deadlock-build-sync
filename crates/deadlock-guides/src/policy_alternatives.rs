use deadlock_data::{Error, EvidenceUnit, Result};

use crate::policy_cards::CoreAlternativeCard;
use crate::policy_claim::{ClaimClass, EvidenceClaim};
use crate::policy_claim_generation::ClaimContext;
use crate::purchase_guide::PurchaseGuide;

pub fn build_core_alternative_cards(
    guide: &PurchaseGuide,
    context: &ClaimContext<'_>,
) -> Result<(Vec<CoreAlternativeCard>, Vec<EvidenceClaim>)> {
    let mut cards = Vec::new();
    let mut claims = Vec::new();
    for alternative in &guide.core_alternatives {
        let alternative = alternative.content();
        let support = alternative
            .support
            .checked_add(alternative.comparison_support)
            .ok_or_else(|| Error::new("Core alternative support exceeds 64 bits"))?;
        let mut claim = context.claim(
            format!(
                "hero/{}/core-alternative/{}-for-{}",
                guide.hero_id, alternative.item_id, alternative.comparator_item_id
            ),
            ClaimClass::Predictive,
            EvidenceUnit::PurchaseEvent,
            support,
            &["estimated", "conditional", "expected"],
        );
        claim.mechanics_refs = alternative
            .mechanics_refs
            .iter()
            .chain(&alternative.comparator_mechanics_refs)
            .cloned()
            .collect();
        claim.estimate = Some(alternative.dr_estimate);
        claim.interval = Some(alternative.comparative_interval);
        claim.comparison_baseline = Some(0.0);
        cards.push(CoreAlternativeCard {
            vs: alternative.vs.clone(),
            why: alternative.why.clone(),
            swap: alternative.swap.clone(),
            when: alternative.when.clone(),
            skip: alternative.skip.clone(),
            mechanics_refs: alternative.mechanics_refs.clone(),
            comparator_mechanics_refs: alternative.comparator_mechanics_refs.clone(),
            item_id: alternative.item_id,
            comparator_item_id: alternative.comparator_item_id,
            stage: u8::try_from(alternative.stage)?,
            evidence_ref: claim.claim_id.clone(),
            support,
            effective_support: alternative.effective_support,
            overlap: alternative.overlap,
            interval: alternative.comparative_interval,
            fold_estimates: alternative.fold_estimates.clone(),
        });
        claims.push(claim);
    }
    Ok((cards, claims))
}
