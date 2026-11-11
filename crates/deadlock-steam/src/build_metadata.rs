use deadlock_data::{Error, Result};
use deadlock_guides::ManagedTrailer;

use crate::binary_reader::BinaryCursor;
use crate::protobuf_fields::{Field, FieldValue, Fields, varint};

/// The fields of a stored hero build that the installer reads.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct HeroBuildMetadata {
    pub build_id: Option<u64>,
    pub hero_id: Option<u64>,
    pub author_account_id: Option<u64>,
    pub name: Option<String>,
    pub description: Option<String>,
    pub publish_timestamp: Option<u64>,
}

impl HeroBuildMetadata {
    /// Returns the managed trailer of a build with the current marker and a valid build path.
    #[must_use]
    pub fn trailer(&self) -> Option<ManagedTrailer> {
        ManagedTrailer::parse(self.description.as_deref()?)
    }

    /// Returns true for a build of this hero that this tool wrote for this account.
    ///
    /// A build with the legacy marker is managed. It has no build path, so an installation
    /// replaces it and `status` reports it as stale.
    #[must_use]
    pub fn is_managed(&self, hero_id: u64, account_id: u32) -> bool {
        self.hero_id == Some(hero_id)
            && self.author_account_id == Some(u64::from(account_id))
            && self
                .description
                .as_deref()
                .is_some_and(ManagedTrailer::is_marked)
    }

    /// Returns the local build ID of a private build of the account.
    ///
    /// Published builds have a publish timestamp and server identifiers. Local identifiers
    /// stay below 1000.
    #[must_use]
    pub fn private_build_id(&self, account_id: u32) -> Option<u64> {
        if self.author_account_id != Some(u64::from(account_id))
            || self
                .publish_timestamp
                .is_some_and(|timestamp| timestamp != 0)
        {
            return None;
        }
        self.build_id.filter(|identifier| *identifier < 1000)
    }
}

/// Reads metadata without changing the original protobuf bytes.
///
/// # Errors
/// Returns an error for malformed protobuf data or invalid metadata text.
pub fn parse_hero_build_metadata(bytes: &[u8]) -> Result<HeroBuildMetadata> {
    let build = extract_build(bytes)?;
    let mut metadata = HeroBuildMetadata::default();
    for field in Fields::new(build)? {
        record_field(&mut metadata, field?)?;
    }
    Ok(metadata)
}

pub fn extract_build(bytes: &[u8]) -> Result<&[u8]> {
    let mut build = None;
    for field in Fields::new(bytes)? {
        let field = field?;
        if let (1, FieldValue::Bytes(candidate)) = (field.number, field.value)
            && is_build(candidate)?
            && build.replace(candidate).is_some()
        {
            return Err(Error::new(
                "Protobuf envelope contains multiple hero builds",
            ));
        }
    }
    Ok(build.unwrap_or(bytes))
}

fn is_build(bytes: &[u8]) -> Result<bool> {
    let mut hero = false;
    let mut name = false;
    for field in Fields::new(bytes)? {
        let field = field?;
        hero |= matches!((field.number, field.value), (2, FieldValue::Integer(_)));
        name |= matches!((field.number, field.value), (5, FieldValue::Bytes(_)));
    }
    Ok(hero && name)
}

fn record_field(metadata: &mut HeroBuildMetadata, field: Field<'_>) -> Result<()> {
    match (field.number, field.value) {
        (1, FieldValue::Integer(value)) => metadata.build_id = Some(value),
        (2, FieldValue::Integer(value)) => metadata.hero_id = Some(value),
        (3, FieldValue::Integer(value)) => metadata.author_account_id = Some(value),
        (5, FieldValue::Bytes(value)) => {
            metadata.name = Some(std::str::from_utf8(value)?.to_owned());
        }
        (6, FieldValue::Bytes(value)) => {
            metadata.description = Some(std::str::from_utf8(value)?.to_owned());
        }
        (13, FieldValue::Integer(value)) => metadata.publish_timestamp = Some(value),
        (11, FieldValue::Bytes(value)) => validate_packed_tags(value)?,
        (1 | 2 | 3 | 5 | 6 | 13, _) => {
            return Err(Error::new(
                "Hero build metadata has an incorrect protobuf wire type",
            ));
        }
        _ => (),
    }
    Ok(())
}

/// Packed tags must decode, so a malformed build is rejected before an installation.
fn validate_packed_tags(bytes: &[u8]) -> Result<()> {
    let mut input = BinaryCursor::new(bytes);
    while input.remaining() > 0 {
        varint(&mut input)?;
    }
    Ok(())
}
