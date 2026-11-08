use deadlock_data::Result;
use serde_json::Value;

use crate::api_session::{ApiSession, object_rows};

pub fn ability_order_stats(
    session: &ApiSession,
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
