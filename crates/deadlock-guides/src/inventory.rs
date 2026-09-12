use deadlock_data::{Error, Result};
use deadlock_input::ItemGraph;

pub const BASE_INVENTORY_SLOTS: usize = 9;
pub const MAX_FLEX_SLOTS: u8 = 3;
pub const MAX_ACTIVE_ITEMS: usize = 4;

#[derive(Clone, Debug, Default, Eq, Ord, PartialEq, PartialOrd)]
pub struct InventoryState {
    owned: Vec<u64>,
    unlocked_flex_slots: u8,
}

impl InventoryState {
    /// # Errors
    /// Returns an error for an invalid flex slot count, item identifier, or inventory size.
    pub fn new(owned: Vec<u64>, unlocked_flex_slots: u8) -> Result<Self> {
        if unlocked_flex_slots > MAX_FLEX_SLOTS {
            return Err(Error::new(
                "Unlocked flex slots must be between zero and three",
            ));
        }
        if owned.contains(&0)
            || owned.len() > BASE_INVENTORY_SLOTS + usize::from(unlocked_flex_slots)
        {
            return Err(Error::new(
                "Inventory has an invalid item identifier or exceeds its capacity",
            ));
        }
        Ok(Self {
            owned,
            unlocked_flex_slots,
        })
    }

    #[must_use]
    pub fn owned(&self) -> &[u64] {
        &self.owned
    }

    #[must_use]
    pub const fn unlocked_flex_slots(&self) -> u8 {
        self.unlocked_flex_slots
    }
}

/// Applies a purchase and consumes its direct components.
///
/// # Errors
/// Returns an error when availability, ownership, flex slot, or active item limits fail.
pub fn purchase_item(
    graph: &ItemGraph,
    state: &InventoryState,
    item_id: u64,
    required_flex_slots: u8,
) -> Result<InventoryState> {
    let item = graph.require(item_id)?;
    if required_flex_slots > state.unlocked_flex_slots {
        return Err(Error::new("Purchase requires unavailable flex capacity"));
    }
    let count = state.owned.iter().filter(|id| **id == item_id).count();
    if (item.unique && count > 0) || u32::try_from(count)? >= item.max_count {
        return Err(Error::new(format!(
            "Item {} exceeds its ownership limit",
            item.name
        )));
    }
    let mut owned = state.owned.clone();
    for component in graph.components(item_id)? {
        remove_one(&mut owned, *component);
    }
    owned.push(item_id);
    let active_count = owned.iter().try_fold(0, |count, id| {
        Ok::<_, Error>(count + usize::from(graph.require(*id)?.active))
    })?;
    if active_count > MAX_ACTIVE_ITEMS {
        return Err(Error::new("Purchase exceeds four active item bindings"));
    }
    InventoryState::new(owned, state.unlocked_flex_slots)
}

/// # Errors
/// Returns an error when the item is unknown or is absent from the inventory.
pub fn sell_item(
    graph: &ItemGraph,
    state: &InventoryState,
    item_id: u64,
) -> Result<InventoryState> {
    graph.require(item_id)?;
    let mut owned = state.owned.clone();
    if !remove_one(&mut owned, item_id) {
        return Err(Error::new(format!(
            "Cannot sell an item outside the inventory: {item_id}"
        )));
    }
    InventoryState::new(owned, state.unlocked_flex_slots)
}

fn remove_one(owned: &mut Vec<u64>, id: u64) -> bool {
    owned
        .iter()
        .position(|owned_id| *owned_id == id)
        .is_some_and(|position| {
            owned.remove(position);
            true
        })
}
