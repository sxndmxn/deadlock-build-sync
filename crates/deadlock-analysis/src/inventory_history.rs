use std::collections::BTreeMap;

use deadlock_data::Result;
use deadlock_input::ItemGraph;
use serde::Deserialize;

pub type Actor = (u64, u64);

#[derive(Clone, Debug, Deserialize)]
pub struct Purchase {
    pub match_id: u64,
    pub player_slot: u64,
    pub item_id: u64,
    pub buy_time: i64,
    pub sold_time: Option<i64>,
}

pub fn inventory_before(purchases: &[Purchase], graph: &ItemGraph, clock: i64) -> Result<Vec<u64>> {
    let mut buckets = BTreeMap::<i64, (Vec<u64>, Vec<u64>)>::new();
    for purchase in purchases
        .iter()
        .filter(|purchase| purchase.buy_time < clock)
    {
        buckets
            .entry(purchase.buy_time)
            .or_default()
            .0
            .push(purchase.item_id);
        if let Some(sold) = purchase.sold_time.filter(|sold| *sold > 0 && *sold < clock) {
            buckets.entry(sold).or_default().1.push(purchase.item_id);
        }
    }
    let mut depths = BTreeMap::new();
    let mut owned = Vec::new();
    for (buys, mut removals) in buckets.into_values() {
        let mut ranked = buys
            .into_iter()
            .map(|item| Ok((component_depth(graph, item, &mut depths)?, item)))
            .collect::<Result<Vec<_>>>()?;
        ranked.sort_unstable();
        for (_, item) in ranked {
            if graph.nodes().contains_key(&item) {
                for component in graph.components(item)? {
                    remove_one(&mut owned, *component);
                }
            }
            owned.push(item);
        }
        removals.sort_unstable();
        for item in removals {
            remove_one(&mut owned, item);
        }
    }
    owned.sort_unstable();
    Ok(owned)
}

fn component_depth(
    graph: &ItemGraph,
    item: u64,
    depths: &mut BTreeMap<u64, usize>,
) -> Result<usize> {
    if let Some(depth) = depths.get(&item) {
        return Ok(*depth);
    }
    let mut depth = 0;
    if graph.nodes().contains_key(&item) {
        for child in graph.components(item)? {
            depth = depth.max(component_depth(graph, *child, depths)? + 1);
        }
    }
    depths.insert(item, depth);
    Ok(depth)
}

fn remove_one(owned: &mut Vec<u64>, item: u64) {
    if let Some(position) = owned.iter().position(|current| *current == item) {
        owned.remove(position);
    }
}
