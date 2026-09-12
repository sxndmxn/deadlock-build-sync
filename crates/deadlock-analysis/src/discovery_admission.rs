use deadlock_data::{Result, count_as_f64, normal_quantile, real};
use deadlock_guides::OutcomeEvidence;
use serde_json::{Value, json};

use crate::core_outcomes::evaluate_core;
use crate::discovery_data::DiscoveryData;
use crate::discovery_models::{Nomination, item_ids};
use crate::purchase_orders::order_evidence;

pub fn admit_nomination(
    data: &DiscoveryData,
    nominee: &Nomination,
    family: u64,
    frozen_hash: &str,
) -> Result<Value> {
    let mut validation = evaluate_core(data, &nominee.candidate.items, "validation")?;
    let selection = OutcomeEvidence::from_document(&nominee.candidate.selection)?;
    let mut limitations = selection
        .limitations(None)?
        .into_iter()
        .map(|reason| format!("selection: {reason}"))
        .collect::<Vec<_>>();
    limitations.extend(
        OutcomeEvidence::from_document(&validation)?
            .limitations(Some(family))?
            .into_iter()
            .map(|reason| format!("validation: {reason}")),
    );
    validation["adjusted_lower_family"] = if validation["adjusted"]["difference"].is_null() {
        Value::Null
    } else {
        (normal_quantile(1.0 - 0.025 / count_as_f64(family.max(1))?)?)
            .mul_add(
                -(real(&validation["adjusted"], "standard_error")?),
                real(&validation["adjusted"], "difference")?,
            )
            .into()
    };
    let ordered = order_evidence(
        data,
        &nominee.candidate.items,
        &item_ids(&nominee.path["order"])?,
        "validation",
    )?;
    if ordered["passes"] != true {
        limitations.push("validation: Frozen order lacks support".into());
    }
    if nominee.tactics["supported_focus"] != true {
        limitations.push(
            nominee.tactics["reason"]
                .as_str()
                .unwrap_or("Mechanic text comparison is unavailable")
                .into(),
        );
    }
    let mut reasons = nominee.candidate.selection_rejections.clone();
    if nominee.path["admitted_before_validation"] != true {
        reasons.push("Frozen order lacks discovery or selection support".into());
    }
    if !nominee.guide.ready {
        reasons.push(
            nominee
                .guide
                .reason
                .clone()
                .unwrap_or_else(|| "Unsupported guide".into()),
        );
    }
    let mut result = serde_json::to_value(nominee)?;
    result["evidence_status"] = if limitations.is_empty() {
        "outcome_supported"
    } else {
        "observed"
    }
    .into();
    result["evidence_limitations"] = json!(limitations);
    result["validation"] = validation;
    result["order_validation"] = ordered;
    result["hypotheses"] = family.into();
    result["rejections"] = json!(reasons);
    result["frozen_sha256"] = frozen_hash.into();
    Ok(result)
}

pub fn discovery_record(row: &Value) -> Result<Value> {
    let mut result = deadlock_data::object(row)?.clone();
    for key in ["guide", "automatic_choices", "branch_candidates"] {
        result.remove(key);
    }
    result.insert("method".into(), "eclat_leiden_pairwise".into());
    result.insert("frozen_guide".into(), row["guide"].clone());
    result.insert("test_evaluated".into(), false.into());
    Ok(result.into())
}
