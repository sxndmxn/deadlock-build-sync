use deadlock_data::{Error, Result};
use deadlock_guides::{LEGACY_MANAGED_MARKER, MANAGED_MARKER};

use crate::binary::{Cursor, check_count};
use crate::protobuf_fields::{Field, FieldValue, Fields, varint};

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct HeroBuildMetadata {
    pub build_id: Option<u64>,
    pub hero_id: Option<u64>,
    pub author_account_id: Option<u64>,
    pub name: Option<String>,
    pub description: Option<String>,
    pub version: Option<u64>,
    pub publish_timestamp: Option<u64>,
    pub tag_ids: Vec<u64>,
}

impl HeroBuildMetadata {
    #[must_use]
    pub fn managed_path(&self) -> Option<&str> {
        let description = self.description.as_deref()?;
        if !description.contains(MANAGED_MARKER) {
            return None;
        }
        description.split('\n').find_map(|line| {
            let path = line.strip_prefix("Build path: ")?.strip_suffix('.')?;
            (!path.is_empty()
                && path
                    .bytes()
                    .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-'))
            .then_some(path)
        })
    }

    #[must_use]
    pub fn is_managed(&self, hero_id: u64, account_id: u32) -> bool {
        self.hero_id == Some(hero_id)
            && self.author_account_id == Some(u64::from(account_id))
            && self.description.as_ref().is_some_and(|description| {
                description.contains(MANAGED_MARKER) || description.contains(LEGACY_MANAGED_MARKER)
            })
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
        (8, FieldValue::Integer(value)) => metadata.version = Some(value),
        (13, FieldValue::Integer(value)) => metadata.publish_timestamp = Some(value),
        (11, FieldValue::Integer(value)) => metadata.tag_ids.push(value),
        (11, FieldValue::Bytes(value)) => read_packed_tags(metadata, value)?,
        (1 | 2 | 3 | 5 | 6 | 8 | 11 | 13, _) => {
            return Err(Error::new(
                "Hero build metadata has an incorrect protobuf wire type",
            ));
        }
        _ => (),
    }
    Ok(())
}

fn read_packed_tags(metadata: &mut HeroBuildMetadata, bytes: &[u8]) -> Result<()> {
    let mut input = Cursor::new(bytes);
    while input.remaining() > 0 {
        check_count(metadata.tag_ids.len() + 1)?;
        metadata.tag_ids.push(varint(&mut input)?);
    }
    Ok(())
}
