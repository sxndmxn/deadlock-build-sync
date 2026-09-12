use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};
use deadlock_input::ItemGraph;
use serde_json::Value;

use crate::ability_definition::{AbilityDefinition, validate_imbue};
use crate::ability_timeline::{AbilityAction, validate_ability_timeline};
use crate::inventory::{InventoryState, purchase_item, sell_item};
use crate::policy_node::{NodeKind, PolicyNode};

#[derive(Clone, Debug)]
pub struct ValidationContext {
    pub item_graph: ItemGraph,
    pub ability_definitions: BTreeMap<u64, AbilityDefinition>,
    pub level_info: Value,
    pub learned_abilities: BTreeSet<u64>,
}

#[derive(Clone, Debug, Default)]
pub struct PolicyPathState {
    pub inventory: InventoryState,
    pub ability_actions: Vec<AbilityAction>,
    pub learned: BTreeSet<u64>,
    pub sell_priorities: Vec<(u64, u32)>,
}

pub fn apply_policy_node(
    node: &PolicyNode,
    state: &PolicyPathState,
    context: &ValidationContext,
) -> Result<PolicyPathState> {
    let mut next = state.clone();
    match node.kind {
        NodeKind::Purchase => apply_purchase(node, &mut next, context)?,
        NodeKind::Sell => {
            let id = node
                .item_id
                .ok_or_else(|| Error::new("Sale node has no item"))?;
            next.inventory = sell_item(&context.item_graph, &next.inventory, id)?;
        }
        NodeKind::Ability => {
            let action = ability_action(node)?;
            next.ability_actions.push(action);
            validate_ability_timeline(
                &context.ability_definitions,
                &context.level_info,
                &next.ability_actions,
            )?;
            next.learned.insert(action.ability_id);
        }
        NodeKind::ObjectiveGate => {
            if let Some(flex) = node.unlocks_flex_slots {
                next.inventory = InventoryState::new(next.inventory.owned().into(), flex)?;
            }
        }
        NodeKind::Choice | NodeKind::Wait | NodeKind::End => (),
    }
    Ok(next)
}

fn apply_purchase(
    node: &PolicyNode,
    state: &mut PolicyPathState,
    context: &ValidationContext,
) -> Result<()> {
    let id = node
        .item_id
        .ok_or_else(|| Error::new("Purchase node has no item"))?;
    if let Some(target) = node.imbue_target_ability_id {
        validate_imbue(
            &context.ability_definitions,
            &state.learned,
            target,
            node.imbue_qualifier.as_deref(),
            node.allow_ultimate_imbue,
        )?;
    }
    state.inventory = purchase_item(
        &context.item_graph,
        &state.inventory,
        id,
        node.required_flex_slots,
    )?;
    if let Some(priority) = node.sell_priority {
        state.sell_priorities.push((id, priority));
    }
    Ok(())
}

pub fn ability_action(node: &PolicyNode) -> Result<AbilityAction> {
    let (level, ability_id) = node
        .level
        .zip(node.ability_id)
        .ok_or_else(|| Error::new("Ability plan has an incomplete action"))?;
    Ok(AbilityAction { level, ability_id })
}
