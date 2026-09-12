use std::collections::BTreeMap;
use std::time::Duration;

use deadlock_data::{Error, Result, array, atomic_write_json, fingerprint, integer};
use deadlock_input::JsonHttpClient;
use serde_json::{Value, json};

use crate::config::RunPaths;

pub fn capture_sources(paths: &RunPaths, base_url: &str) -> Result<Value> {
    let client = JsonHttpClient::new(base_url, Duration::from_secs(120), 5)?;
    client.set_request_interval(Duration::from_millis(310))?;
    let versions = client
        .get_json("/v1/assets/client-versions", &BTreeMap::new())?
        .data;
    let version = array(&versions)?
        .iter()
        .filter_map(Value::as_u64)
        .max()
        .ok_or_else(|| Error::new("Client version response has no numeric version"))?;
    let parameters = BTreeMap::from([("client_version".into(), version.into())]);
    let mut hero_parameters = parameters.clone();
    hero_parameters.insert("only_active".into(), true.into());
    let heroes = client.get_json("/v1/assets/heroes", &hero_parameters)?.data;
    let items = client.get_json("/v1/assets/items", &parameters)?.data;
    let ranks = client.get_json("/v1/assets/ranks", &parameters)?.data;
    let patches = client.get_json("/v2/patches", &BTreeMap::new())?.data;
    let openapi = client.get_json("/openapi.json", &BTreeMap::new())?.data;
    let heroes = selected_rows(&heroes, active_hero)?;
    let shop_items = selected_rows(&items, shop_item)?;
    let result = json!({"client_version":version,"active_heroes":heroes.len(),"shop_items":shop_items.len()});
    let payloads = BTreeMap::from([
        ("client_versions.json", versions),
        ("heroes.json", heroes.into()),
        ("items-all.json", items),
        ("items.json", shop_items.into()),
        ("ranks.json", ranks),
        ("patches.json", patches),
        ("openapi.json", openapi),
    ]);
    let mut hashes = BTreeMap::new();
    for (name, payload) in payloads {
        atomic_write_json(&paths.raw.join(name), &payload)?;
        hashes.insert(name, fingerprint(&payload)?);
    }
    let mut result = result;
    result["source_sha256"] = serde_json::to_value(hashes)?;
    Ok(result)
}

fn selected_rows(document: &Value, predicate: fn(&Value) -> bool) -> Result<Vec<Value>> {
    let rows = array(document)?;
    if rows.iter().any(|row| !row.is_object()) {
        return Err(Error::new("Asset response must contain only objects"));
    }
    let mut rows = rows
        .iter()
        .filter(|row| predicate(row))
        .cloned()
        .collect::<Vec<_>>();
    rows.sort_by_key(|row| row["id"].as_u64());
    for row in &rows {
        integer(row, "id")?;
    }
    Ok(rows)
}

fn active_hero(row: &Value) -> bool {
    row["id"].is_u64()
        && !row["disabled"].as_bool().unwrap_or(false)
        && !row["in_development"].as_bool().unwrap_or(false)
        && row["game_mode"]
            .as_str()
            .unwrap_or("normal")
            .eq_ignore_ascii_case("normal")
}

fn shop_item(row: &Value) -> bool {
    row["id"].is_u64()
        && row["type"] == "upgrade"
        && row["shopable"] == true
        && !row["disabled"].as_bool().unwrap_or(false)
        && row["item_tier"]
            .as_u64()
            .is_some_and(|tier| (1..=4).contains(&tier))
}
