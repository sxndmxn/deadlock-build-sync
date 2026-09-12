use std::collections::BTreeMap;

use deadlock_data::{Error, Result, object};
use serde_json::Value;

#[derive(Clone, Copy, Debug, Default)]
pub struct AbilityGrant {
    pub unlocks: u32,
    pub points: u32,
}

pub type AbilityGrants = BTreeMap<u32, AbilityGrant>;

pub fn parse_ability_grants(level_info: &Value) -> Result<AbilityGrants> {
    let mut grants = BTreeMap::new();
    match level_info {
        Value::Object(rows) => {
            for (level, row) in rows {
                insert_grant(&mut grants, &Value::String(level.clone()), row)?;
            }
        }
        Value::Array(rows) => {
            for row in rows {
                insert_grant(&mut grants, &row["level"], row)?;
            }
        }
        _ => return Err(Error::new("Hero level_info must be an object or an array")),
    }
    if grants.is_empty() {
        return Err(Error::new("Hero level_info contains no levels"));
    }
    Ok(grants)
}

fn insert_grant(grants: &mut AbilityGrants, level: &Value, row: &Value) -> Result<()> {
    let level = level
        .as_u64()
        .or_else(|| {
            level
                .as_str()
                .filter(|level| level.bytes().all(|byte| byte.is_ascii_digit()))?
                .parse()
                .ok()
        })
        .ok_or_else(|| Error::new("Ability grant requires a nonnegative integer level"))?;
    let level = u32::try_from(level)?;
    let grant = parse_grant(row)?;
    if grants.insert(level, grant).is_some() {
        return Err(Error::new("Ability grant levels must be unique"));
    }
    Ok(())
}

fn parse_grant(row: &Value) -> Result<AbilityGrant> {
    let row = object(row)?;
    let mut grant = AbilityGrant {
        points: grant_count(
            row.get("ability_points")
                .or_else(|| row.get("ability_points_granted")),
        )?,
        unlocks: grant_count(row.get("ability_unlocks"))?,
    };
    if let Some(currencies) = row.get("bonus_currencies") {
        let currencies = currencies
            .as_array()
            .ok_or_else(|| Error::new("Ability bonus currencies must be an array"))?;
        for currency in currencies {
            let currency = currency
                .as_str()
                .ok_or_else(|| Error::new("Ability bonus currency must be a string"))?;
            let count = match currency {
                "EAbilityPoints" => Some(&mut grant.points),
                "EAbilityUnlocks" => Some(&mut grant.unlocks),
                _ => None,
            };
            if let Some(count) = count {
                *count = count
                    .checked_add(1)
                    .ok_or_else(|| Error::new("Ability grant exceeds 32 bits"))?;
            }
        }
    }
    Ok(grant)
}

fn grant_count(value: Option<&Value>) -> Result<u32> {
    value.map_or(Ok(0), |value| {
        let count = value
            .as_u64()
            .ok_or_else(|| Error::new("Ability grant must be a nonnegative integer"))?;
        Ok(u32::try_from(count)?)
    })
}
