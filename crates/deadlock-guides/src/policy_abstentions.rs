use deadlock_data::Result;
use deadlock_input::HeroDurationStat;

use crate::duration_profile::summarize_ending_duration_profile;
use crate::policy_model::{Abstention, AbstentionReason};
use crate::purchase_guide::PurchaseGuide;
use crate::situational_evidence::SituationalPolicy;

pub fn build_abstentions(
    guide: &PurchaseGuide,
    duration: &[HeroDurationStat],
    situational: Option<&SituationalPolicy>,
) -> Result<Vec<Abstention>> {
    let mut records = vec![
        abstention(
            AbstentionReason::InadequateSupport,
            "Observed first-ownership net-worth distributions are descriptive. The policy does not give a causal or universally optimal purchase window.",
        ),
        abstention(
            AbstentionReason::InadequateSupport,
            "Joint item and ability acquisition data is not available. The policy does not claim an empirical power spike.",
        ),
        abstention(
            AbstentionReason::TelemetryFailure,
            "Observed adopter outcomes are descriptive associations. These outcomes do not select or order items.",
        ),
    ];
    if let Some(situational) = situational.filter(|policy| !policy.branches().is_empty()) {
        records.extend(
            situational
                .abstentions()
                .iter()
                .map(|detail| abstention(AbstentionReason::InadequateSupport, detail)),
        );
    } else {
        records.push(abstention(AbstentionReason::UnclearThreat, "Tier rows show frequently adopted items. Adoption alone does not identify a situational trigger or counter purchase."));
        records.push(abstention(AbstentionReason::UnclearThreat, "Raw matchup pairs do not establish a mechanical counter. The policy does not give enemy-specific counter claims."));
    }
    let minimum = guide
        .ability_path
        .as_ref()
        .and_then(|path| path.decision_support.iter().min())
        .copied()
        .unwrap_or(0);
    if minimum < 20 {
        records.push(abstention(AbstentionReason::InadequateSupport, &format!("The ability order reaches a legal state with support {minimum}. Treat the remaining order as a default with low confidence.")));
    }
    if summarize_ending_duration_profile(duration, None)?.is_none() {
        records.push(abstention(AbstentionReason::InadequateSupport, "The cohort has no complete, supported ending-duration profile. The policy does not give a phase-strength claim."));
    }
    Ok(records)
}

fn abstention(reason: AbstentionReason, detail: &str) -> Abstention {
    Abstention {
        reason,
        detail: detail.into(),
        node_id: None,
    }
}
