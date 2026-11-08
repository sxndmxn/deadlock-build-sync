use std::error::Error;
use std::fmt::Write as _;
use std::path::{Path, PathBuf};

use sha2::{Digest as _, Sha256};

fn main() -> Result<(), Box<dyn Error>> {
    let manifest = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR")?);
    let root = manifest
        .parent()
        .and_then(Path::parent)
        .ok_or("Analysis crate has no workspace directory")?;
    let mut paths = Vec::new();
    for name in [
        "deadlock-analysis",
        "deadlock-data",
        "deadlock-input",
        "deadlock-guides",
    ] {
        let directory = root.join("crates").join(name);
        if directory.is_dir() {
            collect_sources(&directory, &mut paths)?;
        }
    }
    for name in ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml"] {
        let path = root.join(name);
        if path.is_file() {
            paths.push(path);
        }
    }
    paths.sort();
    for path in &paths {
        println!("cargo:rerun-if-changed={}", path.display());
    }
    println!("cargo:rerun-if-changed=src");
    println!("cargo:rerun-if-changed=sql");
    println!(
        "cargo:rustc-env=DEADLOCK_ANALYSIS_SOURCE_SHA256={}",
        fingerprint_files(root, &paths)?
    );
    // The extraction SQL defines the extracted tables. A resumed run must have the same SQL.
    let mut extraction_sql = Vec::new();
    collect_sources(&manifest.join("sql").join("extract"), &mut extraction_sql)?;
    extraction_sql.sort();
    println!(
        "cargo:rustc-env=DEADLOCK_EXTRACTION_SQL_SHA256={}",
        fingerprint_files(root, &extraction_sql)?
    );
    Ok(())
}

fn fingerprint_files(root: &Path, paths: &[PathBuf]) -> Result<String, Box<dyn Error>> {
    let mut digest = Sha256::new();
    for path in paths {
        let name = path.strip_prefix(root)?.to_string_lossy();
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
    Ok(fingerprint)
}

fn collect_sources(directory: &Path, output: &mut Vec<PathBuf>) -> Result<(), Box<dyn Error>> {
    for entry in std::fs::read_dir(directory)? {
        let entry = entry?;
        let path = entry.path();
        if entry.file_type()?.is_dir() {
            collect_sources(&path, output)?;
        } else if matches!(
            path.extension().and_then(|extension| extension.to_str()),
            Some("rs" | "sql" | "toml")
        ) {
            output.push(path);
        }
    }
    Ok(())
}
