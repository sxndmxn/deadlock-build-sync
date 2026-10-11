use deadlock_data::{Result, sha256};
use deadlock_guides::{
    BuildPresentation, MANAGED_MARKER, PresentationCategory, PresentationContent, PresentationItem,
};
use deadlock_steam::{
    BuildIdentity, BuildSnapshot, Kv3Document, Kv3Kind, Kv3Value, ManagedBuild, encode_hero_build,
    wrap_hero_build,
};
use serde_json::json;

pub fn create_snapshot() -> BuildSnapshot {
    BuildSnapshot {
        snapshot_id: sha256(b"reference snapshot"),
        document: json!({"method":"reference"}),
    }
}

pub fn create_presentation(hero: u64, snapshot: &BuildSnapshot) -> Result<BuildPresentation> {
    let categories = ["MAIN CORE", "TIER 1", "TIER 2", "TIER 3", "TIER 4"]
        .into_iter()
        .enumerate()
        .map(|(index, name)| PresentationCategory {
            name: name.into(),
            description: String::new(),
            width: 100.0,
            height: 100.0,
            optional: index > 0,
            items: if index == 0 {
                vec![PresentationItem {
                    item_id: 1,
                    name: "Reference item".into(),
                    annotation: String::new(),
                    required_flex_slots: None,
                    sell_priority: None,
                    imbue_target_ability_id: None,
                }]
            } else {
                Vec::new()
            },
        })
        .collect();
    BuildPresentation::new(PresentationContent {
        hero_id: hero,
        name: "Reference build".into(),
        tag_ids: [1, 2, 3],
        categories,
        description: format!(
            "{MANAGED_MARKER}\nBuild path: reference.\nSnapshot: {}.",
            snapshot.snapshot_id
        ),
        abilities: None,
    })
}

pub fn create_managed_build(snapshot: &BuildSnapshot) -> Result<ManagedBuild> {
    ManagedBuild::new(
        create_presentation(1, snapshot)?,
        BuildIdentity {
            snapshot_id: snapshot.snapshot_id.clone(),
            build_fingerprint: sha256(b"reference build"),
        },
    )
}

pub fn create_cache(snapshot: &BuildSnapshot) -> Result<Kv3Document> {
    let mut user_build = wrap_hero_build(encode_hero_build(
        &create_presentation(1, snapshot)?,
        17,
        7,
        1,
    )?)?;
    remove_managed_marker(&mut user_build);
    let unrelated = wrap_hero_build(encode_hero_build(
        &create_presentation(2, snapshot)?,
        18,
        7,
        1,
    )?)?;
    let user_value = Kv3Value::new(Kv3Kind::Blob(user_build));
    Ok(Kv3Document::generic(Kv3Value::new(Kv3Kind::Object(vec![
        (
            "Favorites".into(),
            Kv3Value::new(Kv3Kind::Array(vec![user_value.clone()])),
        ),
        (
            "SavedLastUsed".into(),
            Kv3Value::new(Kv3Kind::Array(vec![user_value.clone()])),
        ),
        (
            "LastUsedBuilds".into(),
            Kv3Value::new(Kv3Kind::Unsigned(17)),
        ),
        (
            "Unpublished".into(),
            Kv3Value::new(Kv3Kind::Array(vec![
                user_value,
                Kv3Value::new(Kv3Kind::Blob(unrelated)),
            ])),
        ),
    ]))))
}

fn remove_managed_marker(bytes: &mut [u8]) {
    let marker = MANAGED_MARKER.as_bytes();
    if let Some(start) = bytes
        .windows(marker.len())
        .position(|value| value == marker)
    {
        bytes[start..start + marker.len()].fill(b' ');
    }
}
