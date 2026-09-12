use std::collections::HashSet;

use deadlock_data::{Error, Result};

use crate::binary::{Cursor, MAX_VALUE_COUNT, check_count, check_depth, checked_total};
use crate::kv3_streams::Streams;
use crate::kv3_value::{Kv3Flag, Kv3Kind, Kv3Value};

#[derive(Debug)]
pub struct DecodeBuffers<'data> {
    pub(super) primary: Streams<'data>,
    pub(super) alternate: Option<Streams<'data>>,
    pub(super) types: Cursor<'data>,
    pub(super) objects: Option<Cursor<'data>>,
    pub(super) blobs: Cursor<'data>,
    pub(super) blob_lengths: Vec<usize>,
    pub(super) strings: Vec<String>,
}

#[derive(Debug)]
struct Decoder<'data> {
    buffers: DecodeBuffers<'data>,
    version: u8,
    alternate_active: bool,
    next_blob: usize,
    remaining_values: usize,
    value_bytes: usize,
}

pub fn read_root(buffers: DecodeBuffers<'_>, version: u8) -> Result<Kv3Value> {
    let mut decoder = Decoder {
        buffers,
        version,
        alternate_active: false,
        next_blob: 0,
        remaining_values: MAX_VALUE_COUNT,
        value_bytes: 0,
    };
    let root = decoder.value(0)?;
    decoder.finish()?;
    Ok(root)
}

impl<'data> Decoder<'data> {
    fn streams(&mut self) -> Result<&mut Streams<'data>> {
        if self.alternate_active {
            self.buffers
                .alternate
                .as_mut()
                .ok_or_else(|| Error::new("KV3 array requires a second data buffer"))
        } else {
            Ok(&mut self.buffers.primary)
        }
    }

    fn claim_bytes(&mut self, length: usize) -> Result<()> {
        self.value_bytes = checked_total([self.value_bytes, length])?;
        Ok(())
    }

    fn value_type(&mut self) -> Result<(u8, Kv3Flag)> {
        let tag = self.buffers.types.byte()?;
        if tag & 0x80 == 0 {
            return Ok((tag, Kv3Flag::None));
        }
        let mut encoded_flag = self.buffers.types.byte()?;
        if self.version <= 2 && tag & 0x7f == 6 {
            encoded_flag &= !4;
        }
        let flag = Kv3Flag::decode(encoded_flag, self.version)?;
        let mask = if self.version <= 2 { 0x7f } else { 0x3f };
        Ok((tag & mask, flag))
    }

    fn value(&mut self, depth: usize) -> Result<Kv3Value> {
        let (tag, flag) = self.value_type()?;
        self.typed_value(tag, flag, depth)
    }

    fn typed_value(&mut self, tag: u8, flag: Kv3Flag, depth: usize) -> Result<Kv3Value> {
        check_depth(depth)?;
        self.remaining_values = self
            .remaining_values
            .checked_sub(1)
            .ok_or_else(|| Error::new("KV3 value count exceeds 1,000,000"))?;
        let kind = match tag {
            1 => Kv3Kind::Null,
            2 => self.boolean()?,
            3 => Kv3Kind::Signed(self.streams()?.doubles.i64()?),
            4 => Kv3Kind::Unsigned(self.streams()?.doubles.u64()?),
            5 => Kv3Kind::Float64(self.streams()?.doubles.u64()?),
            6 => Kv3Kind::String(self.string()?),
            7 => Kv3Kind::Blob(self.blob()?),
            8 | 10 | 24 | 25 => self.array(tag, depth)?,
            9 => self.object(depth)?,
            11 => Kv3Kind::Signed(i64::from(self.streams()?.integers.i32()?)),
            12 => Kv3Kind::Unsigned(u64::from(self.streams()?.integers.u32()?)),
            13 => Kv3Kind::Boolean(true),
            14 => Kv3Kind::Boolean(false),
            15 => Kv3Kind::Signed(0),
            16 => Kv3Kind::Signed(1),
            17 => Kv3Kind::Float64(0.0_f64.to_bits()),
            18 => Kv3Kind::Float64(1.0_f64.to_bits()),
            19 => Kv3Kind::Float32(self.streams()?.integers.u32()?),
            20 => Kv3Kind::Signed(i64::from(i16::from_le_bytes(
                self.streams()?.shorts.fixed()?,
            ))),
            21 => Kv3Kind::Unsigned(u64::from(self.streams()?.shorts.u16()?)),
            22 => Kv3Kind::Signed(i64::from(i8::from_le_bytes(self.streams()?.bytes.fixed()?))),
            23 => Kv3Kind::Unsigned(u64::from(self.streams()?.bytes.byte()?)),
            _ => return Err(Error::new(format!("Unsupported KV3 type {tag}"))),
        };
        Ok(Kv3Value { flag, kind })
    }

    fn boolean(&mut self) -> Result<Kv3Kind> {
        match self.streams()?.bytes.byte()? {
            0 => Ok(Kv3Kind::Boolean(false)),
            1 => Ok(Kv3Kind::Boolean(true)),
            _ => Err(Error::new("KV3 boolean must be zero or one")),
        }
    }

    fn string_id(&mut self, identifier: i32) -> Result<String> {
        if identifier == -1 {
            return Ok(String::new());
        }
        let index = usize::try_from(identifier)?;
        let length = self
            .buffers
            .strings
            .get(index)
            .ok_or_else(|| Error::new("KV3 string index exceeds the string table"))?
            .len();
        self.claim_bytes(length)?;
        Ok(self.buffers.strings[index].clone())
    }

    fn string(&mut self) -> Result<String> {
        let identifier = self.streams()?.integers.i32()?;
        self.string_id(identifier)
    }

    fn blob(&mut self) -> Result<Vec<u8>> {
        if self.version == 1 {
            let length = self.streams()?.integers.length()?;
            self.claim_bytes(length)?;
            return Ok(self.streams()?.bytes.read(length)?.to_vec());
        }
        let length = *self
            .buffers
            .blob_lengths
            .get(self.next_blob)
            .ok_or_else(|| Error::new("KV3 blob has no length entry"))?;
        self.next_blob += 1;
        self.claim_bytes(length)?;
        Ok(self.buffers.blobs.read(length)?.to_vec())
    }

    fn array(&mut self, tag: u8, depth: usize) -> Result<Kv3Kind> {
        let count = if tag >= 24 {
            usize::from(self.streams()?.bytes.byte()?)
        } else {
            self.streams()?.integers.count()?
        };
        self.check_children(count)?;
        if tag == 8 {
            return (0..count)
                .map(|_| self.value(depth + 1))
                .collect::<Result<Vec<_>>>()
                .map(Kv3Kind::Array);
        }
        let previous_buffer = self.alternate_active;
        if tag == 25 {
            if self.version != 5 {
                return Err(Error::new("KV3 type 25 requires version 5"));
            }
            self.alternate_active = true;
        }
        let (element_tag, element_flag) = self.value_type()?;
        let values = (0..count)
            .map(|_| self.typed_value(element_tag, element_flag, depth + 1))
            .collect::<Result<Vec<_>>>();
        self.alternate_active = previous_buffer;
        values.map(Kv3Kind::Array)
    }

    fn check_children(&self, count: usize) -> Result<()> {
        check_count(count)?;
        if count > self.remaining_values {
            return Err(Error::new("KV3 children exceed the remaining value limit"));
        }
        Ok(())
    }

    fn object(&mut self, depth: usize) -> Result<Kv3Kind> {
        let count = match &mut self.buffers.objects {
            Some(objects) => objects.count()?,
            None => self.streams()?.integers.count()?,
        };
        self.check_children(count)?;
        let mut names = HashSet::with_capacity(count);
        let mut members = Vec::with_capacity(count);
        for index in 0..count {
            let identifier = self.streams()?.integers.i32()?;
            let name = if identifier == -1 {
                index.to_string()
            } else {
                self.string_id(identifier)?
            };
            if !names.insert(name.clone()) {
                return Err(Error::new(format!(
                    "KV3 object contains duplicate field {name}"
                )));
            }
            members.push((name, self.value(depth + 1)?));
        }
        Ok(Kv3Kind::Object(members))
    }

    fn finish(&self) -> Result<()> {
        self.buffers.primary.finish()?;
        if let Some(alternate) = &self.buffers.alternate {
            alternate.finish()?;
        }
        self.buffers.types.finish("KV3 type stream")?;
        if let Some(objects) = &self.buffers.objects {
            objects.finish("KV3 object count stream")?;
        }
        self.buffers.blobs.finish("KV3 blob stream")?;
        if self.next_blob != self.buffers.blob_lengths.len() {
            return Err(Error::new("KV3 blob length table contains unused entries"));
        }
        Ok(())
    }
}
