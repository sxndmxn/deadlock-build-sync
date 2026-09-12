use deadlock_data::{Error, Result};

use crate::binary::{Cursor, checked_total};

#[derive(Clone, Copy, Debug, Default)]
pub struct Counts {
    pub(super) bytes: usize,
    pub(super) shorts: usize,
    pub(super) integers: usize,
    pub(super) doubles: usize,
}

#[derive(Debug)]
pub struct Header {
    pub(super) version: u8,
    pub(super) format: [u8; 16],
    pub(super) compression: u32,
    pub(super) frame_size: usize,
    pub(super) counts: Counts,
    pub(super) type_size: usize,
    pub(super) decoded_size: usize,
    pub(super) encoded_size: usize,
    pub(super) blob_count: usize,
    pub(super) blob_size: usize,
    pub(super) blob_frame_count: usize,
    pub(super) version5: Option<Version5>,
}

#[derive(Debug)]
pub struct Version5 {
    pub(super) decoded: [usize; 2],
    pub(super) encoded: [usize; 2],
    pub(super) counts: Counts,
    pub(super) object_count: usize,
}

impl Header {
    pub(super) fn read(input: &mut Cursor<'_>) -> Result<Self> {
        let magic = input.fixed::<4>()?;
        if magic[1..] != [0x33, 0x56, 0x4b] || !(2..=5).contains(&magic[0]) {
            return Err(Error::new("Expected binary KV3 version 2, 3, 4, or 5"));
        }
        let version = magic[0];
        let format = input.fixed()?;
        let compression = input.u32()?;
        let dictionary = input.u16()?;
        let frame_size = usize::from(input.u16()?);
        validate_compression(compression, dictionary, frame_size)?;
        let mut counts = Counts {
            bytes: input.length()?,
            integers: input.count()?,
            doubles: input.count()?,
            shorts: 0,
        };
        let type_size = input.length()?;
        input.read(4)?;
        let decoded_size = input.length()?;
        let encoded_size = input.length()?;
        let blob_count = input.count()?;
        let blob_size = input.length()?;
        checked_total([decoded_size, blob_size])?;
        let blob_frame_count = if version >= 4 {
            counts.shorts = input.count()?;
            let frame_bytes = input.length()?;
            if frame_bytes % 2 != 0 {
                return Err(Error::new(
                    "KV3 compressed blob size table has an odd length",
                ));
            }
            frame_bytes / 2
        } else {
            0
        };
        let version5 = (version == 5).then(|| Version5::read(input)).transpose()?;
        Ok(Self {
            version,
            format,
            compression,
            frame_size,
            counts,
            type_size,
            decoded_size,
            encoded_size,
            blob_count,
            blob_size,
            blob_frame_count,
            version5,
        })
    }
}

impl Version5 {
    fn read(input: &mut Cursor<'_>) -> Result<Self> {
        let decoded0 = input.length()?;
        let encoded0 = input.length()?;
        let decoded1 = input.length()?;
        let encoded1 = input.length()?;
        checked_total([decoded0, decoded1])?;
        let counts = Counts {
            bytes: input.length()?,
            shorts: input.count()?,
            integers: input.count()?,
            doubles: input.count()?,
        };
        input.read(4)?;
        let object_count = input.count()?;
        input.read(8)?;
        Ok(Self {
            decoded: [decoded0, decoded1],
            encoded: [encoded0, encoded1],
            counts,
            object_count,
        })
    }
}

fn validate_compression(method: u32, dictionary: u16, frame_size: usize) -> Result<()> {
    if dictionary != 0 {
        return Err(Error::new("KV3 compression dictionaries are not supported"));
    }
    match (method, frame_size) {
        (0 | 2, 0) | (1, 16_384) => Ok(()),
        _ => Err(Error::new(format!(
            "Unsupported KV3 compression method {method} with frame size {frame_size}"
        ))),
    }
}
