use deadlock_data::{Error, Result};

pub const MAX_BINARY_BYTES: usize = 128 * 1024 * 1024;
pub const MAX_VALUE_COUNT: usize = 1_000_000;
pub const MAX_VALUE_DEPTH: usize = 64;

#[derive(Clone, Debug)]
pub struct Cursor<'data> {
    bytes: &'data [u8],
    offset: usize,
}

impl<'data> Cursor<'data> {
    pub(super) const fn new(bytes: &'data [u8]) -> Self {
        Self { bytes, offset: 0 }
    }

    pub(super) const fn remaining(&self) -> usize {
        self.bytes.len() - self.offset
    }

    pub(super) fn read(&mut self, length: usize) -> Result<&'data [u8]> {
        let end = self
            .offset
            .checked_add(length)
            .ok_or_else(|| Error::new("Binary length exceeds the address range"))?;
        let value = self
            .bytes
            .get(self.offset..end)
            .ok_or_else(|| Error::new("Binary data ends before the declared length"))?;
        self.offset = end;
        Ok(value)
    }

    pub(super) fn fixed<const LENGTH: usize>(&mut self) -> Result<[u8; LENGTH]> {
        self.read(LENGTH)?
            .try_into()
            .map_err(|_| Error::new("Binary field has an incorrect length"))
    }

    pub(super) fn byte(&mut self) -> Result<u8> {
        Ok(self.fixed::<1>()?[0])
    }

    pub(super) fn u16(&mut self) -> Result<u16> {
        Ok(u16::from_le_bytes(self.fixed()?))
    }

    pub(super) fn u32(&mut self) -> Result<u32> {
        Ok(u32::from_le_bytes(self.fixed()?))
    }

    pub(super) fn i32(&mut self) -> Result<i32> {
        Ok(i32::from_le_bytes(self.fixed()?))
    }

    pub(super) fn u64(&mut self) -> Result<u64> {
        Ok(u64::from_le_bytes(self.fixed()?))
    }

    pub(super) fn i64(&mut self) -> Result<i64> {
        Ok(i64::from_le_bytes(self.fixed()?))
    }

    pub(super) fn length(&mut self) -> Result<usize> {
        let length = usize::try_from(self.u32()?)?;
        if length > MAX_BINARY_BYTES {
            return Err(Error::new("Binary length exceeds 128 MiB"));
        }
        Ok(length)
    }

    pub(super) fn count(&mut self) -> Result<usize> {
        let count = self.length()?;
        check_count(count)?;
        Ok(count)
    }

    pub(super) fn align(&mut self, alignment: usize) -> Result<()> {
        let padding = (alignment - self.offset % alignment) % alignment;
        self.read(padding)?;
        Ok(())
    }

    pub(super) fn string(&mut self) -> Result<String> {
        let tail = &self.bytes[self.offset..];
        let length = tail
            .iter()
            .position(|byte| *byte == 0)
            .ok_or_else(|| Error::new("KV3 string has no terminator"))?;
        let text = std::str::from_utf8(self.read(length)?)?.to_owned();
        self.byte()?;
        Ok(text)
    }

    pub(super) fn finish(&self, label: &str) -> Result<()> {
        if self.remaining() != 0 {
            return Err(Error::new(format!(
                "{label} contains {} unused bytes",
                self.remaining()
            )));
        }
        Ok(())
    }

    pub(super) fn trailing_padding(&mut self) -> Result<u8> {
        let length = self.remaining();
        if length > 15 || self.read(length)?.iter().any(|byte| *byte != 0) {
            return Err(Error::new("KV3 file has invalid trailing data"));
        }
        Ok(u8::try_from(length)?)
    }
}

pub fn check_count(count: usize) -> Result<()> {
    if count > MAX_VALUE_COUNT {
        return Err(Error::new("KV3 value count exceeds 1,000,000"));
    }
    Ok(())
}

pub fn check_depth(depth: usize) -> Result<()> {
    if depth > MAX_VALUE_DEPTH {
        return Err(Error::new("KV3 nesting depth exceeds 64"));
    }
    Ok(())
}

pub fn checked_total(lengths: impl IntoIterator<Item = usize>) -> Result<usize> {
    let total = lengths
        .into_iter()
        .try_fold(0_usize, usize::checked_add)
        .ok_or_else(|| Error::new("Binary lengths exceed the address range"))?;
    if total > MAX_BINARY_BYTES {
        return Err(Error::new("Combined binary length exceeds 128 MiB"));
    }
    Ok(total)
}
