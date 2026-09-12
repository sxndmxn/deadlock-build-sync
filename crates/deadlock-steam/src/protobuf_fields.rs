use deadlock_data::{Error, Result};

use crate::binary::{Cursor, MAX_VALUE_COUNT, checked_total};

#[derive(Clone, Copy, Debug)]
pub enum FieldValue<'data> {
    Integer(u64),
    Fixed64,
    Bytes(&'data [u8]),
    Fixed32,
}

#[derive(Clone, Copy, Debug)]
pub struct Field<'data> {
    pub number: u32,
    pub value: FieldValue<'data>,
}

#[derive(Debug)]
pub struct Fields<'data> {
    input: Cursor<'data>,
    remaining_fields: usize,
}

impl<'data> Fields<'data> {
    pub(super) fn new(bytes: &'data [u8]) -> Result<Self> {
        checked_total([bytes.len()])?;
        Ok(Self {
            input: Cursor::new(bytes),
            remaining_fields: MAX_VALUE_COUNT,
        })
    }

    fn read(&mut self) -> Result<Field<'data>> {
        self.remaining_fields = self
            .remaining_fields
            .checked_sub(1)
            .ok_or_else(|| Error::new("Protobuf field count exceeds 1,000,000"))?;
        let key = varint(&mut self.input)?;
        let number = u32::try_from(key >> 3)?;
        if number == 0 || number >= 1 << 29 {
            return Err(Error::new(
                "Protobuf field number is outside the permitted range",
            ));
        }
        let value = match key & 7 {
            0 => FieldValue::Integer(varint(&mut self.input)?),
            1 => {
                self.input.read(8)?;
                FieldValue::Fixed64
            }
            2 => {
                let length = usize::try_from(varint(&mut self.input)?)?;
                FieldValue::Bytes(self.input.read(length)?)
            }
            5 => {
                self.input.read(4)?;
                FieldValue::Fixed32
            }
            wire_type => {
                return Err(Error::new(format!(
                    "Unsupported protobuf wire type {wire_type}"
                )));
            }
        };
        Ok(Field { number, value })
    }
}

impl<'data> Iterator for Fields<'data> {
    type Item = Result<Field<'data>>;

    fn next(&mut self) -> Option<Self::Item> {
        if self.input.remaining() == 0 {
            return None;
        }
        let result = self.read();
        if result.is_err() {
            self.input = Cursor::new(&[]);
        }
        Some(result)
    }
}

pub fn varint(input: &mut Cursor<'_>) -> Result<u64> {
    let mut value = 0_u64;
    for shift in (0..70).step_by(7) {
        let byte = input.byte()?;
        if shift == 63 && byte > 1 {
            return Err(Error::new("Protobuf varint exceeds 64 bits"));
        }
        value |= u64::from(byte & 0x7f) << shift;
        if byte < 0x80 {
            return Ok(value);
        }
    }
    Err(Error::new("Protobuf varint has no terminator"))
}
