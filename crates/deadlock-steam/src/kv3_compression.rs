use std::io::Read;

use deadlock_data::{Error, Result};

use crate::binary::{Cursor, MAX_BINARY_BYTES, checked_total};

pub fn decompress(bytes: &[u8], expected: usize, method: u32) -> Result<Vec<u8>> {
    checked_total([expected])?;
    let output = match method {
        0 => bytes.to_vec(),
        1 => lz4_flex::block::decompress(bytes, expected)
            .map_err(|error| Error::new(format!("Invalid KV3 LZ4 block: {error}")))?,
        2 => decompress_zstandard(bytes, expected)?,
        _ => return Err(Error::new("Unsupported KV3 compression method")),
    };
    if output.len() != expected {
        return Err(Error::new(
            "KV3 decompressed length does not match the header",
        ));
    }
    Ok(output)
}

fn decompress_zstandard(bytes: &[u8], expected: usize) -> Result<Vec<u8>> {
    let mut source = bytes;
    let decoder = ruzstd::decoding::StreamingDecoder::new_with_max_window_size(
        &mut source,
        u64::try_from(MAX_BINARY_BYTES)?,
    )
    .map_err(|error| Error::new(format!("Invalid KV3 Zstandard frame: {error}")))?;
    let mut output = Vec::with_capacity(expected);
    decoder
        .take(u64::try_from(expected)? + 1)
        .read_to_end(&mut output)?;
    if !source.is_empty() {
        return Err(Error::new("KV3 Zstandard frame contains trailing data"));
    }
    Ok(output)
}

pub fn decompress_chain(
    input: &mut Cursor<'_>,
    lengths: &[usize],
    encoded: &[usize],
    frame_size: usize,
) -> Result<Vec<u8>> {
    let expected = checked_total(lengths.iter().copied())?;
    let mut output = Vec::with_capacity(expected);
    for encoded_size in encoded {
        let source = input.read(*encoded_size)?;
        let dictionary_start = output.len().saturating_sub(65_536);
        let decoded =
            lz4_flex::block::decompress_with_dict(source, frame_size, &output[dictionary_start..])
                .map_err(|error| Error::new(format!("Invalid KV3 LZ4 chain: {error}")))?;
        if decoded.is_empty() || decoded.len() > expected - output.len() {
            return Err(Error::new("KV3 LZ4 frame exceeds the combined blob length"));
        }
        output.extend_from_slice(&decoded);
    }
    if output.len() != expected {
        return Err(Error::new(
            "KV3 LZ4 chain does not match the combined blob length",
        ));
    }
    Ok(output)
}
