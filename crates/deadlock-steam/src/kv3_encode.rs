use std::collections::{HashMap, HashSet};

use deadlock_data::{Error, Result};

use crate::binary::{MAX_VALUE_COUNT, check_count, check_depth, checked_total};
use crate::kv3_value::{Kv3Document, Kv3Flag, Kv3Kind, Kv3Value, TRAILER};

#[derive(Debug)]
struct Encoder {
    version5: bool,
    objects: Vec<u8>,
    strings: Vec<String>,
    identifiers: HashMap<String, i32>,
    integers: Vec<u8>,
    doubles: Vec<u8>,
    types: Vec<u8>,
    blobs: Vec<u8>,
    blob_lengths: Vec<u32>,
    string_bytes: usize,
    value_bytes: usize,
    remaining_values: usize,
}

impl Encoder {
    fn new(version5: bool) -> Self {
        Self {
            version5,
            objects: Vec::new(),
            strings: Vec::new(),
            identifiers: HashMap::new(),
            integers: if version5 { Vec::new() } else { vec![0; 4] },
            doubles: Vec::new(),
            types: Vec::new(),
            blobs: Vec::new(),
            blob_lengths: Vec::new(),
            string_bytes: 0,
            value_bytes: 0,
            remaining_values: MAX_VALUE_COUNT,
        }
    }

    fn string_id(&mut self, value: &str) -> Result<i32> {
        self.value_bytes = checked_total([self.value_bytes, value.len()])?;
        if value.is_empty() {
            return Ok(-1);
        }
        if value.contains('\0') {
            return Err(Error::new("KV3 strings cannot contain null bytes"));
        }
        if let Some(identifier) = self.identifiers.get(value) {
            return Ok(*identifier);
        }
        self.string_bytes = checked_total([self.string_bytes, value.len(), 1])?;
        check_count(self.strings.len() + 1)?;
        let identifier = i32::try_from(self.strings.len())?;
        self.strings.push(value.to_owned());
        self.identifiers.insert(value.to_owned(), identifier);
        Ok(identifier)
    }

    fn tag(&mut self, tag: u8, flag: Kv3Flag) -> Result<()> {
        let encoded_flag = if self.version5 {
            flag.encode_v5()
        } else {
            flag.encode_v4()?
        };
        if encoded_flag == 0 {
            self.types.push(tag);
        } else {
            self.types.extend_from_slice(&[tag | 0x80, encoded_flag]);
        }
        Ok(())
    }

    fn value(&mut self, value: &Kv3Value, depth: usize) -> Result<()> {
        check_depth(depth)?;
        self.remaining_values = self
            .remaining_values
            .checked_sub(1)
            .ok_or_else(|| Error::new("KV3 value count exceeds 1,000,000"))?;
        let flag = value.flag;
        match &value.kind {
            Kv3Kind::Null => self.tag(1, flag),
            Kv3Kind::Boolean(value) => self.tag(if *value { 13 } else { 14 }, flag),
            Kv3Kind::Signed(value) => self.signed(*value, flag),
            Kv3Kind::Unsigned(value) => self.scalar64(4, value.to_le_bytes(), flag),
            Kv3Kind::Float32(bits) => {
                self.tag(19, flag)?;
                self.integers.extend_from_slice(&bits.to_le_bytes());
                Ok(())
            }
            Kv3Kind::Float64(bits) => self.scalar64(5, bits.to_le_bytes(), flag),
            Kv3Kind::String(value) => self.string(value, flag),
            Kv3Kind::Blob(bytes) => self.blob(bytes, flag),
            Kv3Kind::Array(values) => self.array(values, flag, depth),
            Kv3Kind::Object(members) => self.object(members, flag, depth),
        }
    }

    fn signed(&mut self, value: i64, flag: Kv3Flag) -> Result<()> {
        match value {
            0 => self.tag(15, flag),
            1 => self.tag(16, flag),
            _ => self.scalar64(3, value.to_le_bytes(), flag),
        }
    }

    fn scalar64(&mut self, tag: u8, bytes: [u8; 8], flag: Kv3Flag) -> Result<()> {
        self.tag(tag, flag)?;
        self.doubles.extend_from_slice(&bytes);
        Ok(())
    }

    fn string(&mut self, value: &str, flag: Kv3Flag) -> Result<()> {
        self.tag(6, flag)?;
        let identifier = self.string_id(value)?;
        self.integers.extend_from_slice(&identifier.to_le_bytes());
        Ok(())
    }

    fn blob(&mut self, bytes: &[u8], flag: Kv3Flag) -> Result<()> {
        self.tag(7, flag)?;
        self.value_bytes = checked_total([self.value_bytes, bytes.len()])?;
        self.blob_lengths.push(u32::try_from(bytes.len())?);
        self.blobs.extend_from_slice(bytes);
        Ok(())
    }

    fn array(&mut self, values: &[Kv3Value], flag: Kv3Flag, depth: usize) -> Result<()> {
        check_count(values.len())?;
        self.tag(8, flag)?;
        self.integers
            .extend_from_slice(&u32::try_from(values.len())?.to_le_bytes());
        for value in values {
            self.value(value, depth + 1)?;
        }
        Ok(())
    }

    fn object(
        &mut self,
        members: &[(String, Kv3Value)],
        flag: Kv3Flag,
        depth: usize,
    ) -> Result<()> {
        check_count(members.len())?;
        self.tag(9, flag)?;
        let counts = if self.version5 {
            &mut self.objects
        } else {
            &mut self.integers
        };
        counts.extend_from_slice(&u32::try_from(members.len())?.to_le_bytes());
        let mut names = HashSet::with_capacity(members.len());
        for (name, value) in members {
            if name.is_empty() || !names.insert(name) {
                return Err(Error::new(
                    "KV3 object has an empty or duplicate field name",
                ));
            }
            let identifier = self.string_id(name)?;
            self.integers.extend_from_slice(&identifier.to_le_bytes());
            self.value(value, depth + 1)?;
        }
        Ok(())
    }

    fn payload(&mut self) -> Result<Vec<u8>> {
        if self.version5 {
            return self.payload_v5();
        }
        self.integers[..4].copy_from_slice(&u32::try_from(self.strings.len())?.to_le_bytes());
        let padding = (8 - self.integers.len() % 8) % 8;
        let size = checked_total([
            self.integers.len(),
            padding,
            self.doubles.len(),
            self.string_bytes,
            self.types.len(),
            self.blob_lengths.len() * 4,
            4,
        ])?;
        let mut output = Vec::with_capacity(size);
        output.extend_from_slice(&self.integers);
        output.resize(output.len() + padding, 0);
        output.extend_from_slice(&self.doubles);
        for value in &self.strings {
            output.extend_from_slice(value.as_bytes());
            output.push(0);
        }
        output.extend_from_slice(&self.types);
        for length in &self.blob_lengths {
            output.extend_from_slice(&length.to_le_bytes());
        }
        output.extend_from_slice(&TRAILER.to_le_bytes());
        Ok(output)
    }

    fn header(&self, format: &[u8; 16], payload_size: usize) -> Result<Vec<u8>> {
        if self.version5 {
            return self.header_v5(format, payload_size);
        }
        let mut output = Vec::with_capacity(72);
        output.extend_from_slice(&0x4b56_3304_u32.to_le_bytes());
        output.extend_from_slice(format);
        let fields = [
            0,
            0,
            0,
            self.integers.len() / 4,
            self.doubles.len() / 8,
            self.string_bytes + self.types.len(),
            0,
            payload_size,
            payload_size,
            self.blob_lengths.len(),
            self.blobs.len(),
            0,
            0,
        ];
        for field in fields {
            output.extend_from_slice(&u32::try_from(field)?.to_le_bytes());
        }
        Ok(output)
    }

    fn first_buffer_size(&self) -> Result<usize> {
        checked_total([self.string_bytes.next_multiple_of(4), 4])
    }

    fn payload_v5(&self) -> Result<Vec<u8>> {
        let mut output = Vec::new();
        for value in &self.strings {
            output.extend_from_slice(value.as_bytes());
            output.push(0);
        }
        output.resize(self.string_bytes.next_multiple_of(4), 0);
        output.extend_from_slice(&u32::try_from(self.strings.len())?.to_le_bytes());
        let first_size = output.len();
        output.extend_from_slice(&self.objects);
        output.extend_from_slice(&self.integers);
        if !self.doubles.is_empty() {
            let second_size = (output.len() - first_size).next_multiple_of(8);
            output.resize(checked_total([first_size, second_size])?, 0);
        }
        output.extend_from_slice(&self.doubles);
        output.extend_from_slice(&self.types);
        for length in &self.blob_lengths {
            output.extend_from_slice(&length.to_le_bytes());
        }
        output.extend_from_slice(&TRAILER.to_le_bytes());
        checked_total([output.len()])?;
        Ok(output)
    }

    fn header_v5(&self, format: &[u8; 16], payload_size: usize) -> Result<Vec<u8>> {
        let first_size = self.first_buffer_size()?;
        let second_size = payload_size
            .checked_sub(first_size)
            .ok_or_else(|| Error::new("KV3 second buffer size is invalid"))?;
        let mut output = Vec::with_capacity(120);
        output.extend_from_slice(&0x4b56_3305_u32.to_le_bytes());
        output.extend_from_slice(format);
        let fields = [
            0,
            0,
            self.string_bytes,
            1,
            0,
            self.types.len(),
            0,
            payload_size,
            0,
            self.blob_lengths.len(),
            self.blobs.len(),
            0,
            0,
            first_size,
            0,
            second_size,
            0,
            0,
            0,
            self.integers.len() / 4,
            self.doubles.len() / 8,
            0,
            self.objects.len() / 4,
            0,
            0,
        ];
        for field in fields {
            output.extend_from_slice(&u32::try_from(field)?.to_le_bytes());
        }
        Ok(output)
    }
}

/// Encodes KV3 v4 data. Uses v5 when an entity-name flag requires it.
///
/// # Errors
/// Returns an error when the document exceeds limits or contains an invalid value.
pub fn encode_kv3(document: &Kv3Document) -> Result<Vec<u8>> {
    document.root.object()?;
    if document.trailing_zero_bytes > 15 {
        return Err(Error::new("KV3 trailing padding exceeds 15 bytes"));
    }
    let mut encoder = Encoder::new(requires_v5(&document.root, 0)?);
    encoder.value(&document.root, 0)?;
    let payload = encoder.payload()?;
    let mut output = encoder.header(&document.format, payload.len())?;
    checked_total([
        output.len(),
        payload.len(),
        encoder.blobs.len(),
        4,
        usize::from(document.trailing_zero_bytes),
    ])?;
    output.extend_from_slice(&payload);
    if !encoder.blob_lengths.is_empty() {
        output.extend_from_slice(&encoder.blobs);
        output.extend_from_slice(&TRAILER.to_le_bytes());
    }
    output.resize(output.len() + usize::from(document.trailing_zero_bytes), 0);
    Ok(output)
}

fn requires_v5(value: &Kv3Value, depth: usize) -> Result<bool> {
    check_depth(depth)?;
    if value.flag == Kv3Flag::EntityName {
        return Ok(true);
    }
    match &value.kind {
        Kv3Kind::Array(values) => {
            for value in values {
                if requires_v5(value, depth + 1)? {
                    return Ok(true);
                }
            }
        }
        Kv3Kind::Object(members) => {
            for (_, value) in members {
                if requires_v5(value, depth + 1)? {
                    return Ok(true);
                }
            }
        }
        _ => (),
    }
    Ok(false)
}
