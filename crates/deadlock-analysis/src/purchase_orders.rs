use std::collections::BTreeMap;

use deadlock_data::{Error, Result, count_as_f64, count_ratio};
use deadlock_guides::{InventoryState, SUPPORT, purchase_item, schedule_component_path};
use deadlock_input::ItemGraph;
use serde_json::{Value, json};

use crate::discovery_data::DiscoveryData;

pub fn order_evidence(
    data: &DiscoveryData,
    items: &[u64],
    order: &[u64],
    fold: &str,
) -> Result<Value> {
    let columns = data.columns(items)?;
    let positions = data.columns(order)?;
    let rows = data
        .fold_rows(fold)
        .filter(|row| data.owns(*row, &columns))
        .collect::<Vec<_>>();
    let count = u64::try_from(
        rows.iter()
            .filter(|row| {
                positions
                    .windows(2)
                    .all(|pair| data.times[**row][pair[0]] < data.times[**row][pair[1]])
            })
            .count(),
    )?;
    let owners = u64::try_from(rows.len())?;
    Ok(
        json!({"owners":owners,"ordered_owners":count,"share":count_ratio(count,owners.max(1))?,"passes":SUPPORT.order_supported(owners,count)?}),
    )
}

pub fn select_order(data: &DiscoveryData, items: &[u64], graph: &ItemGraph) -> Result<Value> {
    let columns = data.columns(items)?;
    let rows = data
        .fold_rows("discovery")
        .filter(|row| data.owns(*row, &columns))
        .collect::<Vec<_>>();
    let mut precedence = BTreeMap::new();
    for (first, left) in items.iter().enumerate() {
        for (second, right) in items.iter().enumerate() {
            let count = rows
                .iter()
                .filter(|row| {
                    data.times[**row][columns[first]] < data.times[**row][columns[second]]
                })
                .count();
            precedence.insert((*left, *right), u64::try_from(count)?);
        }
    }
    let mut ranked = Vec::new();
    enumerate_orders(items, &[], 0, &precedence, &mut ranked);
    ranked.sort_by(|left, right| right.0.cmp(&left.0).then_with(|| left.1.cmp(&right.1)));
    let (mut illegal, mut unsupported) = (0_u64, 0_u64);
    for (score, order) in ranked {
        let Ok(actions) = expand_order(&order, graph) else {
            illegal += 1;
            continue;
        };
        let discovery = order_evidence(data, items, &order, "discovery")?;
        let selection = order_evidence(data, items, &order, "selection")?;
        if discovery["passes"] != true || selection["passes"] != true {
            unsupported += 1;
            continue;
        }
        return Ok(
            json!({"method":"pairwise","order":order,"ranking_score":score,"discovery":discovery,"selection":selection,
            "admitted_before_validation":true,"legal":true,"actions":actions,"illegal_orders_skipped":illegal,"reason":null}),
        );
    }
    Ok(
        json!({"method":"pairwise","order":[],"actions":[],"legal":false,"admitted_before_validation":false,"illegal_orders_skipped":illegal,
        "reason":format!("No supported legal order ({illegal} illegal, {unsupported} unsupported)")}),
    )
}

fn enumerate_orders(
    items: &[u64],
    prefix: &[u64],
    score: u64,
    precedence: &BTreeMap<(u64, u64), u64>,
    output: &mut Vec<(u64, Vec<u64>)>,
) {
    if items.len() == prefix.len() {
        output.push((score, prefix.to_vec()));
        return;
    }
    for item in items.iter().filter(|item| !prefix.contains(item)) {
        let mut next = prefix.to_vec();
        next.push(*item);
        let added = prefix
            .iter()
            .map(|prior| precedence[&(*prior, *item)])
            .sum::<u64>();
        enumerate_orders(items, &next, score + added, precedence, output);
    }
}

fn expand_order(order: &[u64], graph: &ItemGraph) -> Result<Vec<Value>> {
    let priorities = order
        .iter()
        .enumerate()
        .map(|(index, item)| Ok((*item, (count_as_f64(u64::try_from(index)?)?, 0.0, *item))))
        .collect::<Result<_>>()?;
    let path = schedule_component_path(graph, order, &priorities)?;
    replay_actions(&path, order, graph)
}

pub fn replay_actions(path: &[u64], order: &[u64], graph: &ItemGraph) -> Result<Vec<Value>> {
    let mut state = InventoryState::default();
    let mut actions = Vec::new();
    let mut spent = 0;
    for item in path.iter().copied() {
        let credit = graph.credited_component_value(item, state.owned())?;
        let cash = graph.incremental_cash_cost(item, state.owned())?;
        state = purchase_item(graph, &state, item, 0)?;
        spent += cash;
        actions.push(json!({"item_id":item,"name":graph.require(item)?.name,"role":if order.contains(&item){"core"}else{"required_component"},
            "component_credit":credit,"incremental_cost":cash,"cumulative_cost":spent,"owned_after":state.owned()}));
    }
    let mut owned = state.owned().to_vec();
    let mut expected = order.to_vec();
    owned.sort_unstable();
    expected.sort_unstable();
    if owned != expected
        || spent
            != order
                .iter()
                .map(|item| graph.require(*item).map(|node| node.cost))
                .collect::<Result<Vec<_>>>()?
                .iter()
                .sum::<u64>()
    {
        return Err(Error::new(
            "Final inventory or component costs differ from the purchase path",
        ));
    }
    Ok(actions)
}
