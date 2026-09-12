use std::collections::BTreeMap;

use deadlock_data::{Error, Result, array, count_ratio, object};
use serde_json::Value;

use crate::build_support::{OutcomeEvidence, SUPPORT};
use crate::evidence_values::{close, finite, integer, nonempty_text};

pub const REFRESH_INSTRUCTION: &str = "Run deadlock-build-sync refresh-evidence, then build again.";

/// # Errors
/// Returns an error when an excluded hero lacks a reason or candidate rejection evidence.
pub fn exclusion_reason(value: &Value) -> Result<String> {
    object(value)?;
    if value["code"].as_str() != Some("no_validated_identity") {
        return Err(Error::new(
            "Hero has no validated builds or supported exclusion",
        ));
    }
    let reason = nonempty_text(&value["reason"], "hero exclusion reason")?;
    let counts = &value["fold_observations"];
    object(counts)?;
    for fold in ["discovery", "selection", "validation"] {
        integer(&counts[fold], "exclusion observations", 0)?;
    }
    let candidates = integer(&value["candidate_count"], "excluded candidate count", 0)?;
    let rejections = array(&value["candidate_rejections"])?;
    if candidates > 0 && rejections.is_empty() {
        return Err(Error::new(
            "Hero exclusion lacks candidate rejection evidence",
        ));
    }
    for rejection in rejections {
        object(rejection)?;
        let reasons = array(&rejection["reasons"])?;
        if reasons.is_empty() {
            return Err(Error::new("Hero exclusion has an empty rejection reason"));
        }
        for reason in reasons {
            nonempty_text(reason, "candidate rejection reason")?;
        }
    }
    Ok(reason.into())
}

/// # Errors
/// Returns an error when frozen discovery does not support the specified core and purchase path.
pub fn validate_discovery(discovery: &Value, core: &[u64], path: &[u64]) -> Result<()> {
    object(discovery)?;
    let method = discovery["method"].as_str();
    if !matches!(method, Some("eclat_leiden_pairwise" | "eclat_leiden_beam"))
        || discovery["test_evaluated"].as_bool() != Some(false)
    {
        return Err(Error::new(format!(
            "Unsupported discovery evidence. {REFRESH_INSTRUCTION}"
        )));
    }
    integer(&discovery["selection_rank"], "frozen selection rank", 0)?;
    let mut sorted = core.to_vec();
    sorted.sort_unstable();
    if !(3..=6).contains(&core.len()) || discovery["items"] != serde_json::to_value(sorted)? {
        return Err(Error::new("Discovery identity differs from the exact core"));
    }
    for key in ["selection", "validation", "path", "frozen_guide"] {
        object(&discovery[key])?;
    }
    for key in ["selection_rejections", "rejections"] {
        if !array(&discovery[key])?.is_empty() {
            return Err(Error::new(
                "A rejected discovery identity cannot be installed",
            ));
        }
    }
    let outcome_supported = validate_outcome_status(discovery)?;
    let order_method = if method == Some("eclat_leiden_beam") {
        "beam16"
    } else {
        "pairwise"
    };
    validate_order(
        &discovery["path"],
        core,
        path,
        &discovery["frozen_guide"],
        order_method,
    )?;
    validate_order_record(&discovery["order_validation"], outcome_supported)
}

fn validate_outcome_status(discovery: &Value) -> Result<bool> {
    let hypotheses = integer(&discovery["hypotheses"], "discovery hypotheses", 1)?;
    let owners = integer(&discovery["discovery_support"], "discovery core owners", 0)?;
    let selection = OutcomeEvidence::from_document(&discovery["selection"])?;
    let validation = OutcomeEvidence::from_document(&discovery["validation"])?;
    if !SUPPORT.core_reasons(owners, selection.owners).is_empty() {
        return Err(Error::new(
            "Discovery core lacks discovery or selection support",
        ));
    }
    let limitations = array(&discovery["evidence_limitations"])?;
    match discovery["evidence_status"].as_str() {
        Some("outcome_supported") => {
            if !limitations.is_empty()
                || !selection.limitations(None)?.is_empty()
                || !validation.limitations(Some(hypotheses))?.is_empty()
            {
                return Err(Error::new(
                    "Discovery core fails its outcome and overlap requirements",
                ));
            }
            if finite(
                &discovery["validation"]["adjusted_lower_family"],
                "family adjusted lower bound",
            )? <= 0.0
            {
                return Err(Error::new("Discovery outcome fails family correction"));
            }
            Ok(true)
        }
        Some("observed") => {
            if limitations.is_empty() {
                return Err(Error::new("Observed discovery lacks evidence limitations"));
            }
            for reason in limitations {
                nonempty_text(reason, "discovery evidence limitation")?;
            }
            Ok(false)
        }
        _ => Err(Error::new("Discovery has no supported evidence status")),
    }
}

fn validate_order(
    order: &Value,
    core: &[u64],
    path: &[u64],
    frozen: &Value,
    method: &str,
) -> Result<()> {
    for fold in ["discovery", "selection"] {
        validate_order_record(&order[fold], true)?;
    }
    if order["order"] != serde_json::to_value(core)?
        || order["method"].as_str() != Some(method)
        || order["legal"].as_bool() != Some(true)
        || order["admitted_before_validation"].as_bool() != Some(true)
        || frozen["ready"].as_bool() != Some(true)
        || frozen["path"] != serde_json::to_value(path)?
    {
        return Err(Error::new(
            "Frozen discovery path differs from its admitted path",
        ));
    }
    Ok(())
}

fn validate_order_record(record: &Value, required: bool) -> Result<()> {
    object(record)?;
    let owners = integer(&record["owners"], "order owners", 0)?;
    let followers = integer(&record["ordered_owners"], "ordered owners", 0)?;
    let passes = SUPPORT.order_supported(owners, followers)?;
    let share = finite(&record["share"], "order share")?;
    if followers > owners || !close(share, count_ratio(followers, owners.max(1))?, 0.0) {
        return Err(Error::new(
            "Discovery purchase order has inconsistent counts",
        ));
    }
    if record["passes"].as_bool() != Some(passes) || (required && !passes) {
        return Err(Error::new("Discovery purchase order lacks support"));
    }
    Ok(())
}

/// # Errors
/// Returns an error for invalid or reversed purchase window boundaries.
pub fn frozen_windows(frozen: &Value) -> Result<BTreeMap<u64, (f64, f64)>> {
    let mut result = BTreeMap::new();
    for (key, value) in object(&frozen["bounds"])? {
        let id = key
            .parse::<u64>()
            .ok()
            .filter(|id| *id > 0)
            .ok_or_else(|| {
                Error::new("Frozen purchase window requires a positive item identifier")
            })?;
        let bounds: [f64; 2] = serde_json::from_value(value.clone())?;
        let [lower, upper] = bounds;
        if !lower.is_finite() || !upper.is_finite() || lower < 0.0 || lower > upper {
            return Err(Error::new(
                "Frozen guide has invalid purchase window boundaries",
            ));
        }
        if result.insert(id, bounds.into()).is_some() {
            return Err(Error::new(
                "Frozen guide repeats a purchase window identifier",
            ));
        }
    }
    Ok(result)
}
