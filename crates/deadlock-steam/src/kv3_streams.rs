use deadlock_data::Result;

use crate::binary::Cursor;
use crate::kv3_header::Counts;

#[derive(Debug)]
pub struct Streams<'data> {
    pub(super) bytes: Cursor<'data>,
    pub(super) shorts: Cursor<'data>,
    pub(super) integers: Cursor<'data>,
    pub(super) doubles: Cursor<'data>,
}

impl<'data> Streams<'data> {
    pub(super) fn read(
        input: &mut Cursor<'data>,
        counts: Counts,
        force_alignment: bool,
    ) -> Result<Self> {
        let bytes = Cursor::new(input.read(counts.bytes)?);
        let shorts = read_aligned(input, counts.shorts, 2, force_alignment)?;
        let integers = read_aligned(input, counts.integers, 4, force_alignment)?;
        let doubles = read_aligned(input, counts.doubles, 8, force_alignment)?;
        Ok(Self {
            bytes,
            shorts,
            integers,
            doubles,
        })
    }

    pub(super) fn finish(&self) -> Result<()> {
        self.bytes.finish("KV3 byte stream")?;
        self.shorts.finish("KV3 short stream")?;
        self.integers.finish("KV3 integer stream")?;
        self.doubles.finish("KV3 double stream")
    }
}

fn read_aligned<'data>(
    input: &mut Cursor<'data>,
    count: usize,
    width: usize,
    force_alignment: bool,
) -> Result<Cursor<'data>> {
    if count > 0 || force_alignment {
        input.align(width)?;
    }
    Ok(Cursor::new(input.read(count * width)?))
}

pub fn read_strings(input: &mut Cursor<'_>, count: usize) -> Result<Vec<String>> {
    (0..count).map(|_| input.string()).collect()
}
