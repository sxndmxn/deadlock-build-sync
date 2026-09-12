use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, array, integer};
use deadlock_guides::THREAT_CLASSES;
use serde_json::{Value, json};

use crate::database::AnalysisDatabase;
use crate::discovery_admission::discovery_record;
use crate::discovery_data::DiscoveryData;
use crate::discovery_models::item_ids;
use crate::item_metrics::load_item_metrics;
use crate::purchase_pool::FrozenGuide;

pub fn build_payload(
    database: &AnalysisDatabase,
    data: &DiscoveryData,
    row: &Value,
    assets: &BTreeMap<u64, Value>,
) -> Result<Value> {
    let items = item_ids(&row["items"])?;
    let members = data.owners(&items, &["discovery", "validation"])?;
    let folds = json!({"train":data.owners(&items,&["discovery"])?.len(),"validation":data.owners(&items,&["validation"])?.len(),"test":0});
    let (metrics, summary) = load_item_metrics(database, &members, data.hero, assets, &folds)?;
    let eligible = integer(&summary, "player_matches")?;
    let frozen: FrozenGuide = serde_json::from_value(row["guide"].clone())?;
    let core = item_ids(&row["path"]["order"])?;
    let actual = metrics
        .iter()
        .map(|item| integer(item, "item_id"))
        .collect::<Result<BTreeSet<_>>>()?;
    if frozen
        .path
        .iter()
        .chain(frozen.pool.values().flatten())
        .any(|item| !actual.contains(item))
    {
        return Err(Error::new(format!(
            "Hero {} has incomplete purchase evidence",
            data.hero
        )));
    }
    let label = array(&row["names"])?
        .iter()
        .take(2)
        .filter_map(Value::as_str)
        .collect::<Vec<_>>()
        .join(" / ");
    let wealth = summary["selection_median_final_net_worth"]
        .as_f64()
        .and_then(|value| num_traits::ToPrimitive::to_u64(&value));
    Ok(
        json!({"path_id":row["identity_id"],"path_label":label,"signature_item_ids":items,"discovery":discovery_record(row)?,
        "eligible_player_matches":eligible,"selection_eligible_player_matches":eligible,"fold_eligible_player_matches":folds,"median_final_net_worth":wealth,"items":metrics,
        "core_policy":{"version":3,"backbone_item_ids":core,"default_item_ids":core,"backbone_matches":eligible,"backbone_fold_matches":folds,"default_matches":eligible,"default_fold_matches":folds,
            "alternatives":[],"candidate_audit":[],"evaluation":{"method":"frozen corrected core validation","validation":row["validation"]}},
        "tier_policy":{"version":1,"item_ids_by_tier":frozen.pool,"source_fold":"discovery","statistics":frozen.pool_statistics},"purchase_timing":frozen.purchase_timing,
        "sequence_policy":{"version":3,"minimum_support":20,"production_model":row["path"]["method"],"component_expanded_default_path":frozen.path,"transitions":[],"evaluation":row["order_validation"]},
        "automatic_choices":row["automatic_choices"],"situational_policy":{"version":2,"threat_vocabulary":THREAT_CLASSES,"branches":[],"abstentions":["Automatic choices require corrected evidence from the same purchase state."]}}),
    )
}
