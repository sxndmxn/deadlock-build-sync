use std::error::Error;
use std::fmt::Write as _;
use std::path::PathBuf;

use sha2::{Digest as _, Sha256};

/// Records the fingerprint of the extraction SQL. A resumed run must have the same SQL,
/// because the SQL defines the extracted tables.
fn main() -> Result<(), Box<dyn Error>> {
    let manifest = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR")?);
    let directory = manifest.join("sql").join("extract");
    let mut paths = Vec::new();
    for entry in std::fs::read_dir(&directory)? {
        let path = entry?.path();
        if path.extension().and_then(|extension| extension.to_str()) == Some("sql") {
            paths.push(path);
        }
    }
    paths.sort();
    println!("cargo:rerun-if-changed={}", directory.display());
    let mut digest = Sha256::new();
    for path in &paths {
        println!("cargo:rerun-if-changed={}", path.display());
        let name = path.strip_prefix(&manifest)?.to_string_lossy();
        let bytes = std::fs::read(path)?;
        digest.update(u64::try_from(name.len())?.to_le_bytes());
        digest.update(name.as_bytes());
        digest.update(u64::try_from(bytes.len())?.to_le_bytes());
        digest.update(bytes);
    }
    let mut fingerprint = String::with_capacity(64);
    for byte in digest.finalize() {
        write!(&mut fingerprint, "{byte:02x}")?;
    }
    println!("cargo:rustc-env=DEADLOCK_EXTRACTION_SQL_SHA256={fingerprint}");
    Ok(())
}
