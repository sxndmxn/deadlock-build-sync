use std::collections::BTreeSet;

use deadlock_data::{
    Error, Result, array, count_ratio, fingerprint, object, sha256, validate_sha256,
};
use serde_json::{Value, json};

use crate::evidence_values::{close, finite, integer, nonempty_text, probability};
use crate::purchase_windows::wilson_score_interval;

pub const BEAM_SCHEMA_VERSION: u64 = 13;
pub const BEAM_METHOD_VERSION: &str = "eclat-leiden-beam16-v2";

/// # Errors
/// Returns an error when generator settings cannot be serialized.
pub fn beam_generator_record() -> Result<Value> {
    let settings = json!({
        "width":16,"prior_strength":1000.0,"uncertainty_multiplier":0.5,"cost_exponent":0.5,
        "discount":0.97,"minimum_item_support":30,"minimum_core_support":200,
        "maximum_core_cost":19200,"minimum_group_similarity":0.5,"ownership_before_seconds":1200,
    });
    Ok(
        json!({"name":"beam","version":BEAM_METHOD_VERSION,"settings_sha256":fingerprint(&settings)?,"settings":settings}),
    )
}

/// # Errors
/// Returns an error when the generator settings or version differ from the supported contract.
pub fn validate_generator_header(value: &Value) -> Result<()> {
    if *value != beam_generator_record()? {
        return Err(Error::new("Beam generator settings or version differ"));
    }
    Ok(())
}

#[derive(Clone, Debug)]
pub struct GeneratorEvidence(Value);

impl GeneratorEvidence {
    /// # Errors
    /// Returns an error when a generator record does not identify the admitted group, core, states, or evidence.
    pub fn from_document(value: &Value, group: &str, core: &[u64], hero_id: u64) -> Result<Self> {
        object(value)?;
        validate_identity(value, group, core, hero_id)?;
        for key in [
            "variant_id",
            "default_variant_id",
            "baseline_path_id",
            "frozen_sha256",
        ] {
            nonempty_text(&value[key], key)?;
        }
        validate_sha256(
            nonempty_text(&value["frozen_sha256"], "beam candidate fingerprint")?,
            "beam candidate fingerprint",
        )?;
        let states = parse_states(&value["states"])?;
        validate_scores(value, &states)?;
        validate_state_evidence(value, &states)?;
        Ok(Self(value.clone()))
    }

    #[must_use]
    pub const fn document(&self) -> &Value {
        &self.0
    }
}

fn validate_identity(value: &Value, group: &str, core: &[u64], hero_id: u64) -> Result<()> {
    if value["group_id"].as_str() != Some(group)
        || value["baseline_path_id"].as_str() != Some(group)
        || !matches!(value["effective"].as_str(), Some("current" | "beam"))
    {
        return Err(Error::new(
            "Beam path has inconsistent group or generator identity",
        ));
    }
    let mut sorted = core.to_vec();
    sorted.sort_unstable();
    if value["core"] != serde_json::to_value(&sorted)? {
        return Err(Error::new(
            "Beam generator core differs from the admitted core",
        ));
    }
    let encoded = format!(
        "[{}]",
        sorted
            .iter()
            .map(u64::to_string)
            .collect::<Vec<_>>()
            .join(", ")
    );
    let expected = format!("{hero_id}-{}", &sha256(encoded.as_bytes())[..16]);
    if value["variant_id"].as_str() != Some(&expected) {
        return Err(Error::new("Beam variant identity differs from its core"));
    }
    Ok(())
}

fn parse_states(value: &Value) -> Result<BTreeSet<String>> {
    let values = array(value)?;
    let mut states = BTreeSet::new();
    for value in values {
        let state = integer(value, "beam wealth state", 0)?;
        if state > 2 || !states.insert(state.to_string()) {
            return Err(Error::new(
                "Beam path has invalid or duplicate wealth states",
            ));
        }
    }
    if states.is_empty() {
        return Err(Error::new("Beam path has no wealth states"));
    }
    Ok(states)
}

fn validate_scores(record: &Value, states: &BTreeSet<String>) -> Result<()> {
    if record["effective"].as_str() == Some("current") {
        nonempty_text(&record["fallback_reason"], "current fallback reason")?;
    } else {
        let scores = object(&record["scores"])?;
        if scores.keys().cloned().collect::<BTreeSet<_>>() != *states {
            return Err(Error::new("Beam path scores differ from its wealth states"));
        }
        for value in scores.values() {
            finite(value, "beam search score")?;
        }
    }
    Ok(())
}

fn validate_state_evidence(record: &Value, states: &BTreeSet<String>) -> Result<()> {
    let evidence = object(&record["state_evidence"])?;
    if evidence.keys().cloned().collect::<BTreeSet<_>>() != *states {
        return Err(Error::new(
            "Beam statistics differ from the declared wealth states",
        ));
    }
    for state in states {
        let folds = object(&evidence[state])?;
        if folds.len() != 3
            || ["discovery", "selection", "validation"]
                .iter()
                .any(|fold| !folds.contains_key(*fold))
        {
            return Err(Error::new("Beam statistics lack separate match partitions"));
        }
        for (fold, value) in folds {
            let count = validate_generator_state(value)?;
            if record["effective"].as_str() == Some("beam") && fold == "discovery" && count < 200 {
                return Err(Error::new("Beam core lacks matched discovery support"));
            }
        }
    }
    Ok(())
}

/// # Errors
/// Returns an error when state counts or intervals are inconsistent with the fixed ownership checkpoint.
pub fn validate_generator_state(value: &Value) -> Result<u64> {
    object(value)?;
    if value["ownership_before_seconds"].as_u64() != Some(1200) {
        return Err(Error::new(
            "Beam statistics use a different ownership checkpoint",
        ));
    }
    let owners = integer(&value["owners"], "core owners", 0)?;
    let wins = integer(&value["wins"], "core wins", 0)?;
    let total = integer(&value["hero_matches"], "state hero matches", 0)?;
    if wins > owners || owners > total {
        return Err(Error::new("Beam core statistics have inconsistent counts"));
    }
    let (lower, upper) = wilson_score_interval(wins, owners, 1.96)?;
    let expected = [
        ("win_rate", count_ratio(wins, owners)?),
        ("lower_95", lower),
        ("upper_95", upper),
    ];
    for (key, rate) in expected {
        validate_rate(&value[key], (owners > 0).then_some(rate), key)?;
    }
    if total == 0 {
        if !value["hero_win_rate"].is_null() {
            return Err(Error::new("An empty hero sample cannot have a win rate"));
        }
    } else {
        probability(&value["hero_win_rate"], "hero baseline win rate")?;
    }
    Ok(owners)
}

fn validate_rate(value: &Value, expected: Option<f64>, label: &str) -> Result<()> {
    if let Some(expected) = expected {
        if !close(finite(value, label)?, expected, 0.0) {
            return Err(Error::new(format!(
                "Beam core statistics have inconsistent {label}"
            )));
        }
    } else if !value.is_null() {
        return Err(Error::new(
            "An empty core sample cannot have outcome statistics",
        ));
    }
    Ok(())
}

/// # Errors
/// Returns an error when group members disagree about their default variant, generator, or frozen candidate family.
pub fn validate_generator_group(
    members: &[(&GeneratorEvidence, &Value)],
    default: &GeneratorEvidence,
) -> Result<()> {
    let default = default.document();
    for (member, discovery) in members {
        let record = member.document();
        if record["default_variant_id"] != default["variant_id"] {
            return Err(Error::new(
                "Beam group has inconsistent default variant references",
            ));
        }
        let beam = record["effective"].as_str() == Some("beam");
        if beam != (discovery["method"].as_str() == Some("eclat_leiden_beam")) {
            return Err(Error::new(
                "Beam effective generator differs from its discovery method",
            ));
        }
        if (beam && record["frozen_sha256"] != discovery["frozen_sha256"])
            || record["frozen_sha256"] != default["frozen_sha256"]
        {
            return Err(Error::new(
                "Beam group contains different frozen candidate families",
            ));
        }
    }
    if !array(&default["states"])?.contains(&Value::from(1)) {
        return Err(Error::new("Beam default requires even-state support"));
    }
    Ok(())
}
