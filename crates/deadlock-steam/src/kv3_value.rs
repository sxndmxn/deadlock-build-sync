use deadlock_data::{Error, Result};

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum Kv3Flag {
    #[default]
    None,
    Resource,
    ResourceName,
    Panorama,
    SoundEvent,
    Subclass,
    EntityName,
}

impl Kv3Flag {
    pub(super) fn decode(value: u8, version: u8) -> Result<Self> {
        match (version, value) {
            (_, 0) => Ok(Self::None),
            (_, 1) => Ok(Self::Resource),
            (_, 2) => Ok(Self::ResourceName),
            (5, 3) | (0..=4, 8) => Ok(Self::Panorama),
            (5, 4) | (0..=4, 16) => Ok(Self::SoundEvent),
            (5, 5) | (0..=4, 32) => Ok(Self::Subclass),
            (5, 6) => Ok(Self::EntityName),
            _ => Err(Error::new(format!(
                "Unsupported KV3 version {version} flag {value}"
            ))),
        }
    }

    pub(super) fn encode_v4(self) -> Result<u8> {
        match self {
            Self::None => Ok(0),
            Self::Resource => Ok(1),
            Self::ResourceName => Ok(2),
            Self::Panorama => Ok(8),
            Self::SoundEvent => Ok(16),
            Self::Subclass => Ok(32),
            Self::EntityName => Err(Error::new("KV3 v4 cannot preserve the entity-name flag")),
        }
    }

    pub(super) const fn encode_v5(self) -> u8 {
        match self {
            Self::None => 0,
            Self::Resource => 1,
            Self::ResourceName => 2,
            Self::Panorama => 3,
            Self::SoundEvent => 4,
            Self::Subclass => 5,
            Self::EntityName => 6,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Kv3Kind {
    Null,
    Boolean(bool),
    Signed(i64),
    Unsigned(u64),
    Float32(u32),
    Float64(u64),
    String(String),
    Blob(Vec<u8>),
    Array(Vec<Kv3Value>),
    Object(Vec<(String, Kv3Value)>),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Kv3Value {
    pub flag: Kv3Flag,
    pub kind: Kv3Kind,
}

impl Kv3Value {
    #[must_use]
    pub const fn new(kind: Kv3Kind) -> Self {
        Self {
            flag: Kv3Flag::None,
            kind,
        }
    }

    /// # Errors
    /// Returns an error when the value is not an object.
    pub fn object(&self) -> Result<&[(String, Self)]> {
        match &self.kind {
            Kv3Kind::Object(members) => Ok(members),
            _ => Err(Error::new("KV3 value must be an object")),
        }
    }

    /// # Errors
    /// Returns an error when the value is not an array.
    pub fn array(&self) -> Result<&[Self]> {
        match &self.kind {
            Kv3Kind::Array(values) => Ok(values),
            _ => Err(Error::new("KV3 value must be an array")),
        }
    }

    /// # Errors
    /// Returns an error when the value is not a binary blob.
    pub fn blob(&self) -> Result<&[u8]> {
        match &self.kind {
            Kv3Kind::Blob(bytes) => Ok(bytes),
            _ => Err(Error::new("KV3 value must be a binary blob")),
        }
    }

    /// # Errors
    /// Returns an error when the object or field is missing.
    pub fn field(&self, name: &str) -> Result<&Self> {
        self.object()?
            .iter()
            .find_map(|(key, value)| (key == name).then_some(value))
            .ok_or_else(|| Error::new(format!("KV3 object has no {name} field")))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Kv3Document {
    pub format: [u8; 16],
    pub root: Kv3Value,
    pub trailing_zero_bytes: u8,
}

pub const GENERIC_FORMAT: [u8; 16] = [
    0x7c, 0x16, 0x12, 0x74, 0xe9, 0x06, 0x98, 0x46, 0xaf, 0xf2, 0xe6, 0x3e, 0xb5, 0x90, 0x37, 0xe7,
];
pub const TRAILER: u32 = 0xffee_dd00;

impl Kv3Document {
    #[must_use]
    pub const fn generic(root: Kv3Value) -> Self {
        Self {
            format: GENERIC_FORMAT,
            root,
            trailing_zero_bytes: 0,
        }
    }
}
