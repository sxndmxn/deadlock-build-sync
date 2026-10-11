use deadlock_data::{
    EpochBoundary, EpochSet, EvidenceRecord, EvidenceUnit, MatchMode, Result, SnapshotContent,
    SnapshotManifest, default_outcome_policy, object, sha256,
};
use deadlock_guides::{
    BuildPresentation, GuideIdentity, MANAGED_MARKER, PresentationCategory, PresentationContent,
    PresentationItem,
};
use deadlock_steam::{
    Kv3Document, Kv3Kind, Kv3Value, ManagedBuild, encode_hero_build, wrap_hero_build,
};
use serde_json::json;

pub fn create_snapshot() -> Result<SnapshotManifest> {
    let boundary = EpochBoundary {
        identity: "reference".into(),
        start_timestamp: 0,
    };
    SnapshotManifest::new(SnapshotContent {
        schema_version: 1,
        client_version: 1,
        as_of_timestamp: 1,
        created_at: "2026-01-01T00:00:00Z".into(),
        match_mode: MatchMode::Ranked,
        game_mode: "normal".into(),
        rank_range: object(&json!({"minimum":{"badge_id":71,"label":"Emissary I"},
            "maximum":{"badge_id":115,"label":"Eternus V"}}))?
        .clone(),
        rank_labels_sha256: sha256(b"ranks"),
        build_tags_sha256: sha256(b"tags"),
        patch: object(&json!({"identity":"reference"}))?.clone(),
        epochs: EpochSet {
            mechanics: boundary.clone(),
            matchmaking: boundary.clone(),
            map_objectives: boundary.clone(),
            telemetry: boundary,
        },
        outcome_policy: default_outcome_policy(true),
        records: vec![EvidenceRecord {
            path: "reference".into(),
            parameters: object(&json!({}))?.clone(),
            fetched_at: "2026-01-01T00:00:00Z".into(),
            sha256: sha256(b"reference"),
            byte_count: 9,
            unit: EvidenceUnit::Asset,
            backend_grain: "reference".into(),
            fallback_behavior: "reject".into(),
            warnings: Vec::new(),
        }],
        warnings: Vec::new(),
    })
}

pub fn create_presentation(hero: u64, snapshot: &SnapshotManifest) -> Result<BuildPresentation> {
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
            "{MANAGED_MARKER}\nBuild path: reference.\nSnapshot: {}.\nPolicy: {}.",
            snapshot.identifier(),
            sha256(b"policy")
        ),
        abilities: None,
    })
}

pub fn create_managed_build(snapshot: &SnapshotManifest) -> Result<ManagedBuild> {
    ManagedBuild::new(
        create_presentation(1, snapshot)?,
        GuideIdentity {
            snapshot_id: snapshot.identifier().into(),
            policy_id: sha256(b"policy"),
            client_version: 1,
            match_mode: MatchMode::Ranked,
            rank_identity: snapshot.rank_identity()?,
            projection_fingerprint: sha256(b"projection"),
        },
    )
}

pub fn create_cache(snapshot: &SnapshotManifest) -> Result<Kv3Document> {
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
