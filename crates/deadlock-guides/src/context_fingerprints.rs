use deadlock_data::{Result, fingerprint, object};
use serde_json::{Map, Value, json};

pub const CONTEXT_SCHEMA_VERSION: u8 = 16;
pub const KIT_BASIS_SCHEMA_VERSION: u8 = 3;
pub const NARRATIVE_BASIS_SCHEMA_VERSION: u8 = 10;

/// # Errors
/// Returns an error when the ability basis cannot serialize.
pub fn calculate_kit_basis_sha256(context: &Value) -> Result<String> {
    fingerprint(
        &json!({"schema_version":KIT_BASIS_SCHEMA_VERSION,"hero_id":context["hero_id"],
        "path_id":context["path_id"],"hero":context["hero"],"hero_mechanics":context["hero_mechanics"],"ability_policy":context["ability_policy"]}),
    )
}

/// # Errors
/// Returns an error when the tactical basis cannot serialize.
pub fn calculate_narrative_basis_sha256(context: &Value) -> Result<String> {
    let policy = context["policy"].as_object().map(|fields| {
        [
            "variant",
            "invariant_kit_id",
            "strategic_role",
            "abstentions",
        ]
        .into_iter()
        .map(|key| (key.to_owned(), fields.get(key).cloned().unwrap_or_default()))
        .collect::<Map<_, _>>()
    });
    let core = context["core"]["items"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|item| item.is_object())
        .map(|item| json!({"item_id":item["item_id"],"item":item["item"],"tier":item["tier"]}))
        .collect::<Vec<_>>();
    fingerprint(
        &json!({"schema_version":NARRATIVE_BASIS_SCHEMA_VERSION,"hero_id":context["hero_id"],"path_id":context["path_id"],
        "path_label":context["path_label"],"hero":context["hero"],"hero_mechanics":context["hero_mechanics"],
        "ability_policy":context["ability_policy"],"core_items":core,"policy_summary":policy}),
    )
}

/// # Errors
/// Returns an error when the hero context is not an object or cannot serialize.
pub fn calculate_context_sha256(context: &Value) -> Result<String> {
    fingerprint_without_field(context, "context_sha256")
}

/// # Errors
/// Returns an error when the context document is not an object or cannot serialize.
pub fn calculate_source_context_sha256(document: &Value) -> Result<String> {
    fingerprint_without_field(document, "source_context_sha256")
}

fn fingerprint_without_field(value: &Value, field: &str) -> Result<String> {
    let mut fields = object(value)?.clone();
    fields.remove(field);
    fingerprint(&fields.into())
}
