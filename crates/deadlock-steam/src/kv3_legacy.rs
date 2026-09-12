use std::collections::HashSet;

use deadlock_data::{Error, Result};

use crate::binary::{Cursor, MAX_VALUE_COUNT, check_depth, checked_total};
use crate::kv3_compression::decompress;
use crate::kv3_streams::read_strings;
use crate::kv3_value::{Kv3Document, Kv3Flag, Kv3Kind, Kv3Value};

const RAW_ENCODING: [u8; 16] = [
    0, 5, 134, 27, 216, 247, 193, 64, 173, 130, 117, 164, 130, 103, 231, 20,
];
const BLOCK_ENCODING: [u8; 16] = [
    70, 26, 121, 149, 188, 149, 108, 79, 167, 11, 5, 188, 161, 183, 223, 210,
];
const LZ4_ENCODING: [u8; 16] = [
    138, 52, 71, 104, 161, 99, 92, 79, 161, 151, 83, 128, 111, 217, 177, 25,
];

#[derive(Debug)]
struct LegacyDecoder<'data> {
    input: Cursor<'data>,
    strings: Vec<String>,
    remaining_values: usize,
    value_bytes: usize,
}

pub fn read_legacy(input: &mut Cursor<'_>) -> Result<Kv3Document> {
    let encoding = input.fixed::<16>()?;
    let format = input.fixed()?;
    let data = match encoding {
        RAW_ENCODING => input.read(input.remaining())?.to_vec(),
        BLOCK_ENCODING => read_compressed_blocks(input)?,
        LZ4_ENCODING => {
            let expected = input.length()?;
            decompress(input.read(input.remaining())?, expected, 1)?
        }
        _ => return Err(Error::new("Legacy KV3 encoding is unsupported")),
    };
    let mut payload = Cursor::new(&data);
    let string_count = payload.count()?;
    let strings = read_strings(&mut payload, string_count)?;
    let mut decoder = LegacyDecoder {
        input: payload,
        strings,
        remaining_values: MAX_VALUE_COUNT,
        value_bytes: 0,
    };
    let root = decoder.value(0)?;
    root.object()?;
    if decoder.input.u32()? != u32::MAX {
        return Err(Error::new("Legacy KV3 trailer is invalid"));
    }
    let trailing_zero_bytes = decoder.input.trailing_padding()? + input.trailing_padding()?;
    if trailing_zero_bytes > 15 {
        return Err(Error::new("KV3 trailing padding exceeds 15 bytes"));
    }
    Ok(Kv3Document {
        format,
        root,
        trailing_zero_bytes,
    })
}

fn read_compressed_blocks(input: &mut Cursor<'_>) -> Result<Vec<u8>> {
    let header = input.u32()?;
    let expected = usize::try_from(header & 0x00ff_ffff)?;
    checked_total([expected])?;
    if header & 0x8000_0000 != 0 {
        return Ok(input.read(expected)?.to_vec());
    }
    let mut output = Vec::with_capacity(expected);
    while output.len() < expected {
        let mask = input.u16()?;
        for bit in 0..16 {
            if output.len() == expected {
                break;
            }
            if mask & (1 << bit) == 0 {
                output.push(input.byte()?);
            } else {
                let token = input.u16()?;
                let distance = usize::from(token >> 4) + 1;
                let count = usize::from(token & 15) + 3;
                if distance > output.len() || count > expected - output.len() {
                    return Err(Error::new("Legacy KV3 block reference exceeds its buffer"));
                }
                for _ in 0..count {
                    output.push(output[output.len() - distance]);
                }
            }
        }
    }
    Ok(output)
}

impl LegacyDecoder<'_> {
    fn value_type(&mut self) -> Result<(u8, Kv3Flag)> {
        let tag = self.input.byte()?;
        if tag & 0x80 == 0 {
            return Ok((tag, Kv3Flag::None));
        }
        let mut flag = self.input.byte()?;
        if tag & 0x7f == 6 {
            flag &= !4;
        }
        Ok((tag & 0x7f, Kv3Flag::decode(flag, 0)?))
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
            2 => match self.input.byte()? {
                0 => Kv3Kind::Boolean(false),
                1 => Kv3Kind::Boolean(true),
                _ => return Err(Error::new("KV3 boolean must be zero or one")),
            },
            3 => Kv3Kind::Signed(self.input.i64()?),
            4 => Kv3Kind::Unsigned(self.input.u64()?),
            5 => Kv3Kind::Float64(self.input.u64()?),
            6 => Kv3Kind::String(self.string()?),
            7 => {
                let length = self.input.length()?;
                self.value_bytes = checked_total([self.value_bytes, length])?;
                Kv3Kind::Blob(self.input.read(length)?.to_vec())
            }
            8 | 10 => self.array(tag, depth)?,
            9 => self.object(depth)?,
            11 => Kv3Kind::Signed(i64::from(self.input.i32()?)),
            12 => Kv3Kind::Unsigned(u64::from(self.input.u32()?)),
            13 => Kv3Kind::Boolean(true),
            14 => Kv3Kind::Boolean(false),
            15 => Kv3Kind::Signed(0),
            16 => Kv3Kind::Signed(1),
            17 => Kv3Kind::Float64(0.0_f64.to_bits()),
            18 => Kv3Kind::Float64(1.0_f64.to_bits()),
            _ => return Err(Error::new(format!("Unsupported legacy KV3 type {tag}"))),
        };
        Ok(Kv3Value { flag, kind })
    }

    fn string(&mut self) -> Result<String> {
        let identifier = self.input.i32()?;
        if identifier == -1 {
            return Ok(String::new());
        }
        let value = self
            .strings
            .get(usize::try_from(identifier)?)
            .ok_or_else(|| Error::new("KV3 string index exceeds the string table"))?;
        self.value_bytes = checked_total([self.value_bytes, value.len()])?;
        Ok(value.clone())
    }

    fn child_count(&mut self) -> Result<usize> {
        let count = self.input.count()?;
        if count > self.remaining_values {
            return Err(Error::new("KV3 children exceed the remaining value limit"));
        }
        Ok(count)
    }

    fn array(&mut self, tag: u8, depth: usize) -> Result<Kv3Kind> {
        let count = self.child_count()?;
        let element_type = (tag == 10).then(|| self.value_type()).transpose()?;
        (0..count)
            .map(|_| match element_type {
                Some((tag, flag)) => self.typed_value(tag, flag, depth + 1),
                None => self.value(depth + 1),
            })
            .collect::<Result<Vec<_>>>()
            .map(Kv3Kind::Array)
    }

    fn object(&mut self, depth: usize) -> Result<Kv3Kind> {
        let count = self.child_count()?;
        let mut names = HashSet::with_capacity(count);
        let mut members = Vec::with_capacity(count);
        for index in 0..count {
            let name = self.string()?;
            let name = if name.is_empty() {
                index.to_string()
            } else {
                name
            };
            if !names.insert(name.clone()) {
                return Err(Error::new(
                    "Legacy KV3 object contains a duplicate field name",
                ));
            }
            members.push((name, self.value(depth + 1)?));
        }
        Ok(Kv3Kind::Object(members))
    }
}
