use std::collections::BTreeMap;

use deadlock_data::{Error, Result};
use deadlock_guides::{
    BuildPresentation, PresentationAbilities, PresentationCategory, PresentationContent,
    PresentationItem,
};
use prost::Message;

use crate::binary_reader::checked_total;
use crate::build_metadata::extract_build;
use crate::protobuf_schema::{
    AbilityOrder, AbilityPurchase, Category, Details, Envelope, HeroBuild, ItemModification,
};

/// Encodes a validated presentation as a Steam hero build.
///
/// # Errors
/// Returns an error for an invalid build identity, ability order, or excessive output size.
pub fn encode_hero_build(
    presentation: &BuildPresentation,
    build_id: u64,
    account_id: u32,
    timestamp: u64,
) -> Result<Vec<u8>> {
    if build_id == 0 || account_id == 0 {
        return Err(Error::new("Build and account IDs must be positive"));
    }
    let content = presentation.content();
    let build = HeroBuild {
        build_id,
        hero_id: content.hero_id,
        author_account_id: u64::from(account_id),
        timestamp,
        name: content.name.clone(),
        description: content.description.clone(),
        update_timestamp: 0,
        version: 0,
        source_build_id: 0,
        details: build_presentation_details(content)?,
        tag_ids: content.tag_ids.to_vec(),
        published: false,
    };
    checked_total([build.encoded_len()])?;
    Ok(build.encode_to_vec())
}

/// # Errors
/// Returns an error when the encoded build exceeds the binary size limit.
pub fn wrap_hero_build(build: Vec<u8>) -> Result<Vec<u8>> {
    let envelope = Envelope {
        build,
        user_data: Vec::new(),
        status: 0,
        timestamp: 0,
    };
    checked_total([envelope.encoded_len()])?;
    Ok(envelope.encode_to_vec())
}

pub fn same_build_content(previous: &[u8], current: &[u8]) -> Result<bool> {
    let decode = |bytes: &[u8]| {
        HeroBuild::decode(bytes).map_err(|error| Error::new(format!("Invalid hero build: {error}")))
    };
    let mut previous = decode(extract_build(previous)?)?;
    let mut current = decode(extract_build(current)?)?;
    previous.timestamp = 0;
    current.timestamp = 0;
    Ok(previous == current)
}

pub fn matches_presentation(bytes: &[u8], presentation: &BuildPresentation) -> Result<bool> {
    let installed = HeroBuild::decode(extract_build(bytes)?)
        .map_err(|error| Error::new(format!("Invalid hero build: {error}")))?;
    let expected = presentation.content();
    Ok(installed.hero_id == expected.hero_id
        && installed.description == expected.description
        && installed.tag_ids == expected.tag_ids
        && installed.details == build_presentation_details(expected)?)
}

fn build_presentation_details(content: &PresentationContent) -> Result<Details> {
    Ok(Details {
        categories: content.categories.iter().map(build_category).collect(),
        abilities: content
            .abilities
            .as_ref()
            .map(build_ability_order)
            .transpose()?,
    })
}

fn build_item_modification(value: &PresentationItem) -> ItemModification {
    ItemModification {
        item_id: value.item_id,
        annotation: value.annotation.clone(),
        required_flex_slots: value.required_flex_slots,
        sell_priority: value.sell_priority,
        imbue_target_ability_id: value.imbue_target_ability_id,
    }
}

fn build_category(value: &PresentationCategory) -> Category {
    Category {
        items: value.items.iter().map(build_item_modification).collect(),
        name: value.name.clone(),
        description: value.description.clone(),
        width: value.width,
        height: value.height,
        optional: value.optional,
    }
}

fn build_ability_order(value: &PresentationAbilities) -> Result<AbilityOrder> {
    let mut counts = BTreeMap::<u64, usize>::new();
    let mut purchases = Vec::with_capacity(value.ability_ids.len());
    for (index, ability_id) in value.ability_ids.iter().enumerate() {
        let count = counts.entry(*ability_id).or_default();
        let (currency_type, delta) = match *count {
            0 => (2, -1),
            1 => (1, -1),
            2 => (1, -2),
            3 => (1, -5),
            _ => {
                return Err(Error::new(
                    "Ability order contains more than four purchases for one ability",
                ));
            }
        };
        *count += 1;
        purchases.push(AbilityPurchase {
            ability_id: *ability_id,
            currency_type,
            delta,
            annotation: (index == 0).then(|| value.annotation.clone()),
        });
    }
    Ok(AbilityOrder { purchases })
}
