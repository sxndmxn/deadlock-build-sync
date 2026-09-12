use std::collections::BTreeMap;

use deadlock_data::{Error, EvidenceSemantics, EvidenceUnit, Result};
use serde_json::Value;

use crate::api_session::{ApiSession, object_rows};

#[derive(Clone, Debug)]
pub struct HeroDurationStat {
    pub label: String,
    pub min_duration_s: u32,
    pub max_duration_s: u32,
    pub wins: u32,
    pub losses: u32,
    pub matches: u32,
}

impl HeroDurationStat {
    #[must_use]
    pub fn win_rate(&self) -> f64 {
        if self.matches == 0 {
            0.0
        } else {
            f64::from(self.wins) / f64::from(self.matches)
        }
    }
}

pub fn item_stats(
    session: &mut ApiSession,
    hero_id: u64,
    minimum_timestamp: i64,
    minimum_matches: u32,
    bucket: Option<&str>,
) -> Result<Vec<Value>> {
    let grain = bucket.map_or_else(
        || "purchase-event".to_owned(),
        |bucket| format!("purchase-event-by-{bucket}"),
    );
    session.recorder.declare("/v1/analytics/item-stats", EvidenceSemantics { unit: EvidenceUnit::PurchaseEvent, backend_grain: grain, fallback_behavior: "reject; no adoption-rate substitution".into(), warnings: vec!["The matches field counts purchase events. One player appearance can contain multiple purchase events.".into()] })?;
    let mut parameters = session.analytic_parameters(minimum_timestamp)?;
    parameters.insert("hero_id".into(), hero_id.into());
    parameters.insert("min_matches".into(), minimum_matches.into());
    if let Some(bucket) = bucket {
        parameters.insert("bucket".into(), bucket.into());
    }
    object_rows(
        session.get("/v1/analytics/item-stats", parameters)?,
        "Item statistics",
    )
}

pub fn ability_order_stats(
    session: &mut ApiSession,
    hero_id: u64,
    minimum_timestamp: i64,
    minimum_matches: u32,
    item_ids: &[u64],
) -> Result<Vec<Value>> {
    let mut parameters = session.analytic_parameters(minimum_timestamp)?;
    parameters.extend([
        ("hero_id".into(), hero_id.into()),
        ("min_matches".into(), minimum_matches.into()),
        ("min_ability_upgrades".into(), 1.into()),
        ("max_ability_upgrades".into(), 16.into()),
    ]);
    if !item_ids.is_empty() {
        parameters.insert(
            "include_item_ids".into(),
            item_ids.iter().copied().map(Value::from).collect(),
        );
    }
    object_rows(
        session.get("/v1/analytics/ability-order-stats", parameters)?,
        "Ability order statistics",
    )
}

pub fn hero_counter_stats(
    session: &mut ApiSession,
    minimum_timestamp: i64,
    same_lane: bool,
) -> Result<Vec<Value>> {
    let mut parameters = session.analytic_parameters(minimum_timestamp)?;
    parameters.insert("same_lane_filter".into(), same_lane.into());
    object_rows(
        session.get("/v1/analytics/hero-counter-stats", parameters)?,
        "Hero counter statistics",
    )
}

pub fn hero_stats_by_duration(
    session: &mut ApiSession,
    minimum_timestamp: i64,
) -> Result<BTreeMap<u64, Vec<HeroDurationStat>>> {
    let mut curves = BTreeMap::<u64, Vec<HeroDurationStat>>::new();
    for (label, minimum, maximum) in [
        ("<25m", 0, 1500),
        ("25–30m", 1500, 1800),
        ("30–35m", 1800, 2100),
        ("35–40m", 2100, 2400),
        ("40–45m", 2400, 2700),
        ("45–50m", 2700, 3000),
        ("50m+", 3000, 7000),
    ] {
        let mut parameters = session.analytic_parameters(minimum_timestamp)?;
        parameters.extend([
            ("bucket".into(), "no_bucket".into()),
            ("min_duration_s".into(), minimum.into()),
            ("max_duration_s".into(), (maximum - 1).into()),
        ]);
        let rows = session.get("/v1/analytics/hero-stats", parameters)?;
        let rows = rows
            .as_array()
            .ok_or_else(|| Error::new("Hero duration statistics must be a list"))?;
        for row in rows {
            if let Some((hero_id, statistic)) = duration_statistic(row, label, minimum, maximum) {
                curves.entry(hero_id).or_default().push(statistic);
            }
        }
    }
    Ok(curves)
}

fn duration_statistic(
    row: &Value,
    label: &str,
    minimum: u32,
    maximum: u32,
) -> Option<(u64, HeroDurationStat)> {
    let hero_id = row["hero_id"].as_u64()?;
    let matches = u32::try_from(row["matches"].as_u64()?).ok()?;
    let wins = u32::try_from(row["wins"].as_u64()?).ok()?;
    let losses = u32::try_from(row["losses"].as_u64()?).ok()?;
    if matches < 20 || wins.checked_add(losses)? != matches {
        return None;
    }
    Some((
        hero_id,
        HeroDurationStat {
            label: label.into(),
            min_duration_s: minimum,
            max_duration_s: maximum,
            wins,
            losses,
            matches,
        },
    ))
}
