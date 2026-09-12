use std::collections::BTreeMap;

use deadlock_data::{Error, Result};
use serde_json::{Value, json};

use crate::policy_model::BuildPolicy;

pub fn describe_policy_actions(
    policy: Option<&BuildPolicy>,
    assets: &BTreeMap<u64, &Value>,
) -> Result<Vec<Value>> {
    let Some(policy) = policy else {
        return Ok(Vec::new());
    };
    let content = policy.content();
    let claims = content
        .evidence
        .iter()
        .map(|claim| (&claim.claim_id, claim))
        .collect::<BTreeMap<_, _>>();
    let cards = content
        .counter_cards
        .iter()
        .map(|card| (&card.evidence_ref, card))
        .collect::<BTreeMap<_, _>>();
    let mut actions = Vec::new();
    for node in &content.nodes {
        let Some(reference) = &node.evidence_ref else {
            continue;
        };
        let claim = claims
            .get(reference)
            .ok_or_else(|| Error::new("Policy action has no evidence claim"))?;
        let action_id = node.item_id.or(node.ability_id);
        let asset = action_id
            .and_then(|id| assets.get(&id).copied())
            .unwrap_or(&Value::Null);
        let name = asset["name"]
            .as_str()
            .filter(|name| !name.is_empty())
            .map_or_else(
                || action_id.map_or_else(|| node.node_id.clone(), |id| id.to_string()),
                str::to_owned,
            );
        let mut action = json!({"node_id":node.node_id,"kind":node.kind,"action_id":action_id,"action":name,
            "evidence_ref":reference,"claim_class":claim.claim_class,"language_ceiling":claim.language_ceiling,
            "mechanics_refs":claim.mechanics_refs,"annotation":node.annotation});
        if let Some(card) = cards.get(reference) {
            let mut contract = serde_json::to_value(card)?;
            contract["item"] = asset_name(asset, card.item_id).into();
            contract["comparator_item"] = asset_name(
                assets
                    .get(&card.comparator_item_id)
                    .copied()
                    .unwrap_or(&Value::Null),
                card.comparator_item_id,
            )
            .into();
            action["conditional_contract"] = contract;
        }
        actions.push(action);
    }
    Ok(actions)
}

fn asset_name(asset: &Value, id: u64) -> String {
    asset["name"]
        .as_str()
        .filter(|name| !name.is_empty())
        .map_or_else(|| format!("Item {id}"), str::to_owned)
}
