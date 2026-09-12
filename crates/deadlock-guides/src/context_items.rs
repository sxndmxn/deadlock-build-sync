use std::collections::BTreeMap;

use deadlock_data::Result;
use serde_json::{Map, Value, json};

use crate::guide_item::{GuideItem, format_purchase_window};
use crate::purchase_guide::PurchaseGuide;

pub fn strategy_tiers(guide: &PurchaseGuide, assets: &BTreeMap<u64, &Value>) -> Map<String, Value> {
    [(1, "I"), (2, "II"), (3, "III"), (4, "IV")]
        .into_iter()
        .map(|(tier, label)| {
            let items = guide
                .tiers
                .get(&tier)
                .into_iter()
                .flatten()
                .enumerate()
                .map(|(index, item)| {
                    tier_item(
                        item,
                        index + 1,
                        assets.get(&item.item_id).copied().unwrap_or(&Value::Null),
                    )
                })
                .collect::<Vec<_>>();
            (label.into(), items.into())
        })
        .collect()
}

fn tier_item(item: &GuideItem, rank: usize, asset: &Value) -> Value {
    let mut value = json!({"item_id":item.item_id,"item":item.name,
        "slot":asset["item_slot_type"].as_str().filter(|slot| !slot.is_empty()).unwrap_or("unknown").to_uppercase(),
        "is_active_item":asset["is_active_item"]==true,"claim_class":"descriptive"});
    let fields = if item.eligible_player_matches > 0 {
        json!({"rank_by_first_ownership_net_worth":rank,"purchase_adoption":item.purchase_adoption,
            "adopter_matches":item.adopter_matches,"eligible_player_matches":item.eligible_player_matches,"purchase_events":item.purchase_events,
            "observed_outcome_rate_among_adopters":item.observed_outcome_rate,"median_first_ownership_time_s":item.median_buy_time_s,
            "median_valid_first_ownership_net_worth":item.median_valid_buy_net_worth,"first_ownership_net_worth_q25":item.buy_net_worth_q25,
            "first_ownership_net_worth_q75":item.buy_net_worth_q75,"valid_first_ownership_net_worth_share":item.valid_buy_net_worth_share,
            "unit":"eligible_player_appearance"})
    } else {
        json!({"rank_by_purchase_event_volume":rank,"observed_purchase_event_net_worth_ranges":item.windows.iter().map(|window| json!({
            "label":format_purchase_window(window),"observed_outcome_rate":window.observed_outcome_rate,"purchase_event_observations":window.matches})).collect::<Vec<_>>(),
            "relative_purchase_event_volume":item.relative_purchase_event_volume,"observed_outcome_rate":item.observed_outcome_rate,
            "purchase_event_observations":item.purchase_event_observations,"unit":"purchase_event"})
    };
    if let (Some(value), Some(fields)) = (value.as_object_mut(), fields.as_object()) {
        value.extend(fields.clone());
    }
    value
}

pub fn core_context(guide: &PurchaseGuide) -> Result<Value> {
    let selection = if guide.evidence_summary["generator"]["effective"] == "beam" {
        "frozen group and supported state-aware beam component path"
    } else {
        "frozen Eclat identity, Leiden group, and supported pairwise component path"
    };
    Ok(
        json!({"selection":selection,"backbone_item_ids":guide.backbone_items.iter().map(|item| item.item_id).collect::<Vec<_>>(),
            "backbone_player_matches":guide.backbone_matches,"backbone_share":guide.backbone_share,
            "item_ids_in_observed_acquisition_order":guide.core_items.iter().map(|item| item.item_id).collect::<Vec<_>>(),
            "component_expanded_purchase_path":guide.core_path_items().iter().map(|item| item.item_id).collect::<Vec<_>>(),
            "joint_player_matches":guide.core_joint_matches,"joint_share":guide.core_joint_share,
            "eligible_player_matches":guide.core_items.first().map_or(0, |item| item.eligible_player_matches),
            "median_final_net_worth":guide.median_final_net_worth,"core_target_cost":guide.core_target_cost,
            "items":guide.core_items.iter().map(core_item).collect::<Vec<_>>(),
            "optional_core_substitution_cards":guide.core_alternatives.iter().map(crate::core_alternative::CoreAlternativeEvidence::to_document).collect::<Result<Vec<_>>>()?,
        }),
    )
}

fn core_item(item: &GuideItem) -> Value {
    json!({"item_id":item.item_id,"item":item.name,"purchase_adoption":item.purchase_adoption,"adopter_matches":item.adopter_matches,
        "eligible_player_matches":item.eligible_player_matches,"observed_outcome_rate_among_adopters":item.observed_outcome_rate,
        "median_first_ownership_time_s":item.median_buy_time_s,"median_valid_first_ownership_net_worth":item.median_valid_buy_net_worth})
}
