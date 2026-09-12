use std::collections::BTreeSet;

use deadlock_data::{Error, Result, fingerprint, sha256};
use serde_json::{Map, Number, Value, json};

use crate::build_metadata::parse_hero_build_metadata;
use crate::kv3_value::{Kv3Document, Kv3Kind, Kv3Value};

pub fn unmanaged_fingerprint(
    document: &Kv3Document,
    account_id: u32,
    hero_ids: &BTreeSet<u64>,
) -> Result<String> {
    let mut output = Map::new();
    for (name, value) in document.root.object()? {
        let value = if name == "Unpublished" {
            value
                .array()?
                .iter()
                .filter(|value| !target_build(value, account_id, hero_ids))
                .map(normalize)
                .collect::<Result<Vec<_>>>()?
                .into()
        } else {
            normalize(value)?
        };
        output.insert(name.clone(), value);
    }
    fingerprint(&Value::Object(output))
}

fn target_build(value: &Kv3Value, account_id: u32, hero_ids: &BTreeSet<u64>) -> bool {
    value
        .blob()
        .ok()
        .and_then(|bytes| parse_hero_build_metadata(bytes).ok())
        .is_some_and(|metadata| {
            metadata.hero_id.is_some_and(|hero_id| {
                hero_ids.contains(&hero_id) && metadata.is_managed(hero_id, account_id)
            })
        })
}

fn normalize(value: &Kv3Value) -> Result<Value> {
    match &value.kind {
        Kv3Kind::Null => Ok(Value::Null),
        Kv3Kind::Boolean(value) => Ok((*value).into()),
        Kv3Kind::Signed(value) => Ok((*value).into()),
        Kv3Kind::Unsigned(value) => Ok((*value).into()),
        Kv3Kind::Float32(bits) => normalize_float(f64::from(f32::from_bits(*bits))),
        Kv3Kind::Float64(bits) => normalize_float(f64::from_bits(*bits)),
        Kv3Kind::String(value) => Ok(value.clone().into()),
        Kv3Kind::Blob(bytes) => Ok(json!({"bytes_sha256":sha256(bytes)})),
        Kv3Kind::Array(values) => values
            .iter()
            .map(normalize)
            .collect::<Result<Vec<_>>>()
            .map(Value::Array),
        Kv3Kind::Object(members) => members
            .iter()
            .map(|(name, value)| normalize(value).map(|value| (name.clone(), value)))
            .collect::<Result<Map<_, _>>>()
            .map(Value::Object),
    }
}

fn normalize_float(value: f64) -> Result<Value> {
    Number::from_f64(value)
        .map(Value::Number)
        .ok_or_else(|| Error::new("Steam cache fingerprint cannot represent a nonfinite number"))
}
