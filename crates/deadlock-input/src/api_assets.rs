use deadlock_data::{Error, RankCatalog, Result};
use serde_json::{Map, Value};

use crate::api_session::{ApiSession, object_rows};

pub fn active_heroes(session: &mut ApiSession) -> Result<Vec<Value>> {
    let mut parameters = session.asset_parameters()?;
    parameters.insert("only_active".into(), true.into());
    let rows = object_rows(session.get("/v1/assets/heroes", parameters)?, "Hero assets")?;
    let mut heroes = Vec::new();
    for hero in rows {
        if hero["id"].as_u64().is_some_and(|id| id > 0)
            && !boolean(&hero, "disabled")?
            && !boolean(&hero, "in_development")?
            && normal_game_mode(&hero)?
        {
            heroes.push(hero);
        }
    }
    heroes.sort_by_key(|hero| hero["id"].as_u64());
    Ok(heroes)
}

pub fn items(session: &mut ApiSession) -> Result<Vec<Value>> {
    let parameters = session.asset_parameters()?;
    let rows = object_rows(session.get("/v1/assets/items", parameters)?, "Item assets")?;
    let mut items = Vec::new();
    for item in rows {
        if normal_game_mode(&item)? {
            items.push(item);
        }
    }
    Ok(items)
}

pub fn build_tags(session: &mut ApiSession) -> Result<Vec<Value>> {
    let parameters = session.asset_parameters()?;
    object_rows(
        session.get("/v1/assets/build-tags", parameters)?,
        "Build tag assets",
    )
}

pub fn rank_catalog(session: &mut ApiSession) -> Result<RankCatalog> {
    let parameters = session.asset_parameters()?;
    let rows = object_rows(session.get("/v1/assets/ranks", parameters)?, "Rank assets")?;
    RankCatalog::from_assets(&rows)
}

pub fn steam_persona(session: &mut ApiSession, account_id: u32) -> Result<String> {
    let parameters = Map::from_iter([("account_ids".into(), account_id.into())]);
    let rows = object_rows(
        session.get("/v1/players/steam", parameters)?,
        "Steam profile",
    )?;
    rows.first()
        .and_then(|row| row["personaname"].as_str())
        .map(str::trim)
        .filter(|name| !name.is_empty())
        .map(str::to_owned)
        .ok_or_else(|| Error::new(format!("Steam profile {account_id} has no persona name")))
}

fn boolean(value: &Value, name: &str) -> Result<bool> {
    match value.get(name) {
        None => Ok(false),
        Some(Value::Bool(value)) => Ok(*value),
        Some(_) => Err(Error::new(format!("Asset {name} must be a boolean"))),
    }
}

fn normal_game_mode(value: &Value) -> Result<bool> {
    match value.get("game_mode") {
        None | Some(Value::Null) => Ok(true),
        Some(Value::String(mode)) => Ok(mode.is_empty() || mode.eq_ignore_ascii_case("normal")),
        Some(_) => Err(Error::new("Asset game mode must be a string")),
    }
}
