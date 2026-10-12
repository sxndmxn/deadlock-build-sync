use deadlock_data::{Error, Result, sha256};
use deadlock_guides::{HeroBuildCatalog, ImbueTarget, build_hero_presentation};
use deadlock_steam::{encode_hero_build, wrap_hero_build};
use prost::Message as _;

#[path = "../../../deadlock-steam/src/protobuf_schema.rs"]
mod protobuf_schema;

pub fn check_imbue_encoding() -> Result<()> {
    let catalog: HeroBuildCatalog = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/imbue-catalog.json"
    ))?;
    catalog.validate()?;
    let root = tempfile::tempdir()?;
    let path = root.path().join("hero-builds.json");
    catalog.write(&path)?;
    let restored = HeroBuildCatalog::read(&path)?;
    if catalog != restored {
        return Err(Error::new(
            "Catalog serialization changed the imbue targets",
        ));
    }
    let build = catalog
        .heroes
        .first()
        .ok_or_else(|| Error::new("Imbue fixture has no hero"))?;
    let presentation =
        build_hero_presentation(build, &catalog, &sha256(b"imbue fixture"), "Reference")?;
    let bytes = encode_hero_build(&presentation, 1, 7, 1)?;
    let wrapped = wrap_hero_build(bytes)?;
    let envelope = protobuf_schema::Envelope::decode(wrapped.as_slice())
        .map_err(|error| Error::new(format!("Cannot decode the imbue envelope: {error}")))?;
    let decoded = protobuf_schema::HeroBuild::decode(envelope.build.as_slice())
        .map_err(|error| Error::new(format!("Cannot decode the imbue reference: {error}")))?;
    let targets = decoded
        .details
        .categories
        .iter()
        .flat_map(|category| &category.items)
        .map(|item| (item.item_id, item.imbue_target_ability_id))
        .collect::<Vec<_>>();
    if targets != [(10, Some(101)), (16, None), (17, Some(102))] {
        return Err(Error::new(
            "Steam encoding lost or changed a native imbue target",
        ));
    }
    check_invalid_catalogs(&catalog)
}

fn check_invalid_catalogs(catalog: &HeroBuildCatalog) -> Result<()> {
    for (ability_id, matches, observations) in [
        (0, 30, 40),
        (999, 30, 40),
        (101, 19, 19),
        (101, 20, 40),
        (101, 21, 20),
    ] {
        let mut invalid = catalog.clone();
        invalid.heroes[0].core[0].imbue_target = Some(ImbueTarget {
            ability_id,
            matches,
            observations,
        });
        if invalid.validate().is_ok() {
            return Err(Error::new(
                "Catalog accepted an invalid native imbue target",
            ));
        }
    }
    let mut old = catalog.clone();
    old.schema_version = 3;
    if old.validate().is_ok() {
        return Err(Error::new(
            "Catalog accepted the schema without imbue selection",
        ));
    }
    Ok(())
}
