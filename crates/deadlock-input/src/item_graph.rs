use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};
use serde_json::Value;

use crate::item_node::ItemNode;

type ItemRelations = BTreeMap<u64, Vec<u64>>;

#[derive(Clone, Debug)]
pub struct ItemGraph {
    nodes: BTreeMap<u64, ItemNode>,
    by_class: BTreeMap<String, u64>,
    components: ItemRelations,
    children: ItemRelations,
    ancestors: ItemRelations,
}

impl ItemGraph {
    /// # Errors
    /// Returns an error for missing components, duplicate identifiers, or a component cycle.
    pub fn from_assets(assets: &[Value]) -> Result<Self> {
        let mut nodes = BTreeMap::new();
        for asset in assets {
            if let Some(node) = ItemNode::from_asset(asset)?
                && nodes.insert(node.item_id, node).is_some()
            {
                return Err(Error::new("Item identifiers must be unique"));
            }
        }
        Self::new(nodes)
    }

    /// # Errors
    /// Returns an error for invalid nodes, missing components, or a component cycle.
    pub fn new(nodes: BTreeMap<u64, ItemNode>) -> Result<Self> {
        if nodes.is_empty() || nodes.len() > 4096 {
            return Err(Error::new("Item graph requires between 1 and 4096 items"));
        }
        let by_class = validate_nodes(&nodes)?;
        let (components, children) = resolve_components(&nodes, &by_class)?;
        let ancestors = collect_ancestors(&components)?;
        Ok(Self {
            nodes,
            by_class,
            components,
            children,
            ancestors,
        })
    }

    #[must_use]
    pub const fn nodes(&self) -> &BTreeMap<u64, ItemNode> {
        &self.nodes
    }

    /// # Errors
    /// Returns an error when the current assets do not contain the item.
    pub fn require(&self, id: u64) -> Result<&ItemNode> {
        self.nodes
            .get(&id)
            .ok_or_else(|| Error::new(format!("Unknown current item: {id}")))
    }

    #[must_use]
    pub fn by_class(&self, class_name: &str) -> Option<&ItemNode> {
        self.by_class
            .get(class_name)
            .and_then(|id| self.nodes.get(id))
    }

    /// # Errors
    /// Returns an error when the current assets do not contain the item.
    pub fn components(&self, id: u64) -> Result<&[u64]> {
        relation(&self.components, id)
    }

    /// # Errors
    /// Returns an error when the current assets do not contain the item.
    pub fn children(&self, id: u64) -> Result<&[u64]> {
        relation(&self.children, id)
    }

    /// Returns component identifiers in dependency order, with each identifier present once.
    ///
    /// # Errors
    /// Returns an error when the current assets do not contain the item.
    pub fn transitive_components(&self, id: u64) -> Result<&[u64]> {
        relation(&self.ancestors, id)
    }

    /// # Errors
    /// Returns an error when the item is unknown or the component credit exceeds 64 bits.
    pub fn credited_component_value(&self, id: u64, owned: &[u64]) -> Result<u64> {
        self.components(id)?
            .iter()
            .filter(|component| owned.contains(component))
            .try_fold(0_u64, |total, component| {
                total
                    .checked_add(self.require(*component)?.cost)
                    .ok_or_else(|| Error::new("Component credit exceeds 64 bits"))
            })
    }

    /// # Errors
    /// Returns an error when the item is unknown or its component credit is invalid.
    pub fn incremental_cash_cost(&self, id: u64, owned: &[u64]) -> Result<u64> {
        Ok(self
            .require(id)?
            .cost
            .saturating_sub(self.credited_component_value(id, owned)?))
    }

    /// # Errors
    /// Returns an error when the current assets do not contain the item.
    pub fn total_tree_investment(&self, id: u64) -> Result<u64> {
        Ok(self.require(id)?.cost)
    }
}

fn validate_nodes(nodes: &BTreeMap<u64, ItemNode>) -> Result<BTreeMap<String, u64>> {
    let mut classes = BTreeMap::new();
    for (id, node) in nodes {
        if *id == 0 || *id != node.item_id || node.max_count == 0 || node.class_name.is_empty() {
            return Err(Error::new(
                "Item node has an invalid identifier, class, or ownership limit",
            ));
        }
        if classes.insert(node.class_name.clone(), *id).is_some() {
            return Err(Error::new("Item class names must be unique"));
        }
        if node.component_classes.iter().collect::<BTreeSet<_>>().len()
            != node.component_classes.len()
        {
            return Err(Error::new(format!(
                "Item {} repeats a direct component",
                node.name
            )));
        }
    }
    Ok(classes)
}

fn resolve_components(
    nodes: &BTreeMap<u64, ItemNode>,
    by_class: &BTreeMap<String, u64>,
) -> Result<(ItemRelations, ItemRelations)> {
    let mut components = BTreeMap::new();
    let mut children = nodes
        .keys()
        .map(|id| (*id, Vec::new()))
        .collect::<BTreeMap<_, _>>();
    for (id, node) in nodes {
        let mut resolved = Vec::new();
        for name in &node.component_classes {
            let component = *by_class.get(name).ok_or_else(|| {
                Error::new(format!(
                    "Item {} references a missing component: {name}",
                    node.name
                ))
            })?;
            resolved.push(component);
            children.entry(component).or_default().push(*id);
        }
        components.insert(*id, resolved);
    }
    Ok((components, children))
}

fn collect_ancestors(components: &ItemRelations) -> Result<ItemRelations> {
    let mut result = ItemRelations::new();
    let mut pending = components.keys().copied().collect::<BTreeSet<_>>();
    while !pending.is_empty() {
        let ready = pending
            .iter()
            .copied()
            .filter(|id| components[id].iter().all(|id| result.contains_key(id)))
            .collect::<Vec<_>>();
        if ready.is_empty() {
            return Err(Error::new("Item component graph contains a cycle"));
        }
        for id in ready {
            let mut ordered = Vec::new();
            let mut seen = BTreeSet::new();
            for component in &components[&id] {
                for ancestor in result[component].iter().chain(std::iter::once(component)) {
                    if seen.insert(*ancestor) {
                        ordered.push(*ancestor);
                    }
                }
            }
            result.insert(id, ordered);
            pending.remove(&id);
        }
    }
    Ok(result)
}

fn relation(relations: &ItemRelations, id: u64) -> Result<&[u64]> {
    relations
        .get(&id)
        .map(Vec::as_slice)
        .ok_or_else(|| Error::new(format!("Unknown current item: {id}")))
}
