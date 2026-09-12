use deadlock_data::{Error, Result};

use crate::binary::{Cursor, checked_total};
use crate::kv3_compression::{decompress, decompress_chain};
use crate::kv3_decode::{DecodeBuffers, read_root};
use crate::kv3_header::{Counts, Header};
use crate::kv3_legacy::read_legacy;
use crate::kv3_streams::{Streams, read_strings};
use crate::kv3_value::{Kv3Document, Kv3Kind, TRAILER};

/// Reads binary KV3 data without access to Steam files.
///
/// # Errors
/// Returns an error for unsupported formats, malformed data, or exceeded resource limits.
pub fn decode_kv3(bytes: &[u8]) -> Result<Kv3Document> {
    checked_total([bytes.len()])?;
    let mut input = Cursor::new(bytes);
    if bytes.starts_with(b"VKV\x03") {
        input.read(4)?;
        return read_legacy(&mut input);
    }
    if bytes.starts_with(b"\x013VK") {
        input.read(4)?;
        return read_v1(&mut input);
    }
    let header = Header::read(&mut input)?;
    let root = if header.version == 5 {
        read_v5(&mut input, &header)?
    } else {
        read_v2_v4(&mut input, &header)?
    };
    let trailing_zero_bytes = input.trailing_padding()?;
    if !matches!(root.kind, Kv3Kind::Object(_)) {
        return Err(Error::new("KV3 root must be an object"));
    }
    Ok(Kv3Document {
        format: header.format,
        root,
        trailing_zero_bytes,
    })
}

fn read_v1(input: &mut Cursor<'_>) -> Result<Kv3Document> {
    let format = input.fixed()?;
    let compression = input.u32()?;
    if compression > 1 {
        return Err(Error::new("KV3 version 1 requires raw or LZ4 data"));
    }
    let counts = Counts {
        bytes: input.length()?,
        integers: input.count()?,
        doubles: input.count()?,
        shorts: 0,
    };
    let expected = input.length()?;
    let encoded = if compression == 0 {
        expected
    } else {
        input.remaining()
    };
    let data = decompress(input.read(encoded)?, expected, compression)?;
    let mut payload = Cursor::new(&data);
    let mut primary = Streams::read(&mut payload, counts, true)?;
    let strings = read_strings(&mut payload, primary.integers.count()?)?;
    let type_size = payload
        .remaining()
        .checked_sub(4)
        .ok_or_else(|| Error::new("KV3 version 1 trailer is missing"))?;
    let types = Cursor::new(payload.read(type_size)?);
    read_trailer(&mut payload)?;
    let buffers = DecodeBuffers {
        primary,
        alternate: None,
        types,
        objects: None,
        blobs: Cursor::new(&[]),
        blob_lengths: Vec::new(),
        strings,
    };
    let root = read_root(buffers, 1)?;
    root.object()?;
    Ok(Kv3Document {
        format,
        root,
        trailing_zero_bytes: input.trailing_padding()?,
    })
}

fn read_v2_v4(input: &mut Cursor<'_>, header: &Header) -> Result<crate::kv3_value::Kv3Value> {
    let expected = if header.compression == 2 {
        checked_total([header.decoded_size, header.blob_size])?
    } else {
        header.decoded_size
    };
    let data = decompress(
        input.read(header.encoded_size)?,
        expected,
        header.compression,
    )?;
    let mut payload = Cursor::new(&data);
    let mut primary = Streams::read(&mut payload, header.counts, true)?;
    let mut types = Cursor::new(payload.read(header.type_size)?);
    let strings = read_strings(&mut types, primary.integers.count()?)?;
    let lengths = read_blob_lengths(&mut payload, header)?;
    let blobs = read_older_blobs(input, &mut payload, header, &lengths)?;
    payload.finish("KV3 data buffer")?;
    if header.blob_count > 0 {
        read_trailer(input)?;
    }
    let buffers = DecodeBuffers {
        primary,
        alternate: None,
        types,
        objects: None,
        blobs: Cursor::new(&blobs),
        blob_lengths: lengths,
        strings,
    };
    read_root(buffers, header.version)
}

fn read_older_blobs(
    input: &mut Cursor<'_>,
    payload: &mut Cursor<'_>,
    header: &Header,
    lengths: &[usize],
) -> Result<Vec<u8>> {
    match header.compression {
        0 if payload.remaining() == header.blob_size => {
            Ok(payload.read(header.blob_size)?.to_vec())
        }
        0 => Ok(input.read(header.blob_size)?.to_vec()),
        1 => {
            let frame_count = if header.version >= 4 {
                header.blob_frame_count
            } else {
                payload.remaining() / 2
            };
            let frames = read_frame_lengths(payload, frame_count)?;
            decompress_chain(input, lengths, &frames, header.frame_size)
        }
        2 => Ok(payload.read(header.blob_size)?.to_vec()),
        _ => Err(Error::new("Unsupported KV3 blob compression")),
    }
}

fn read_v5(input: &mut Cursor<'_>, header: &Header) -> Result<crate::kv3_value::Kv3Value> {
    let version5 = header
        .version5
        .as_ref()
        .ok_or_else(|| Error::new("KV3 version 5 header is missing"))?;
    if checked_total(version5.decoded)? != header.decoded_size {
        return Err(Error::new(
            "KV3 data buffer lengths do not match the header",
        ));
    }
    let sizes = if header.compression == 0 {
        version5.decoded
    } else {
        version5.encoded
    };
    let data0 = decompress(
        input.read(sizes[0])?,
        version5.decoded[0],
        header.compression,
    )?;
    let data1 = decompress(
        input.read(sizes[1])?,
        version5.decoded[1],
        header.compression,
    )?;
    let mut payload0 = Cursor::new(&data0);
    let mut alternate = Streams::read(&mut payload0, header.counts, false)?;
    let strings = read_strings(&mut alternate.bytes, alternate.integers.count()?)?;
    payload0.finish("KV3 first data buffer")?;
    let mut payload1 = Cursor::new(&data1);
    let objects = Cursor::new(payload1.read(version5.object_count * 4)?);
    let primary = Streams::read(&mut payload1, version5.counts, false)?;
    let types = Cursor::new(payload1.read(header.type_size)?);
    let lengths = read_blob_lengths(&mut payload1, header)?;
    let frames = read_frame_lengths(&mut payload1, header.blob_frame_count)?;
    payload1.finish("KV3 second data buffer")?;
    let blobs = read_v5_blobs(input, header, &lengths, &frames)?;
    if header.blob_count > 0 {
        read_trailer(input)?;
    }
    let buffers = DecodeBuffers {
        primary,
        alternate: Some(alternate),
        types,
        objects: Some(objects),
        blobs: Cursor::new(&blobs),
        blob_lengths: lengths,
        strings,
    };
    read_root(buffers, header.version)
}

fn read_v5_blobs(
    input: &mut Cursor<'_>,
    header: &Header,
    lengths: &[usize],
    frames: &[usize],
) -> Result<Vec<u8>> {
    if header.blob_size == 0 {
        if !frames.is_empty() {
            return Err(Error::new("Empty KV3 blobs have compressed frames"));
        }
        return Ok(Vec::new());
    }
    match header.compression {
        0 => Ok(input.read(header.blob_size)?.to_vec()),
        1 => decompress_chain(input, lengths, frames, header.frame_size),
        2 => {
            let version5 = header
                .version5
                .as_ref()
                .ok_or_else(|| Error::new("KV3 version 5 header is missing"))?;
            let data_size = checked_total(version5.encoded)?;
            let size = header
                .encoded_size
                .checked_sub(data_size)
                .ok_or_else(|| Error::new("KV3 compressed blob length is negative"))?;
            decompress(input.read(size)?, header.blob_size, 2)
        }
        _ => Err(Error::new("Unsupported KV3 blob compression")),
    }
}

fn read_blob_lengths(payload: &mut Cursor<'_>, header: &Header) -> Result<Vec<usize>> {
    let lengths = (0..header.blob_count)
        .map(|_| payload.length())
        .collect::<Result<Vec<_>>>()?;
    if checked_total(lengths.iter().copied())? != header.blob_size {
        return Err(Error::new("KV3 blob lengths do not match the header"));
    }
    read_trailer(payload)?;
    Ok(lengths)
}

fn read_frame_lengths(payload: &mut Cursor<'_>, count: usize) -> Result<Vec<usize>> {
    (0..count).map(|_| payload.u16().map(usize::from)).collect()
}

fn read_trailer(input: &mut Cursor<'_>) -> Result<()> {
    if input.u32()? != TRAILER {
        return Err(Error::new("KV3 trailer is invalid"));
    }
    Ok(())
}
