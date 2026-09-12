use std::fmt::Write as _;
use std::io::Read as _;
use std::path::Path;

use sha2::{Digest as _, Sha256};

use crate::Result;

/// # Errors
/// Returns an error when the file cannot be opened or read.
pub fn file_sha256(path: &Path) -> Result<String> {
    let mut source = std::fs::File::open(path)?;
    let mut digest = Sha256::new();
    let mut buffer = vec![0_u8; 1024 * 1024];
    loop {
        let count = source.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    let mut output = String::with_capacity(64);
    for byte in digest.finalize() {
        write!(&mut output, "{byte:02x}")?;
    }
    Ok(output)
}
