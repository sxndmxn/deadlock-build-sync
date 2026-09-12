use std::path::Path;
use std::process::Command;

use serde_json::Value;

use crate::error::Result;

pub fn check(root: &Path, expected_files: usize) -> Result<()> {
    let version = Command::new("arch-lint").arg("--version").output()?;
    if !version.status.success()
        || std::str::from_utf8(&version.stdout)?.trim() != "arch-lint 0.6.0"
    {
        return Err("Architecture checks require arch-lint-cli 0.6.0".into());
    }
    let output = Command::new("arch-lint")
        .arg("--config")
        .arg(root.join("arch-lint.toml"))
        .args(["check", "--engine", "syn", "--format", "json"])
        .arg(root)
        .current_dir(root)
        .output()?;
    if !output.status.success() {
        return Err(format!(
            "Arch-lint failed:\n{}\n{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        )
        .into());
    }
    let source = std::str::from_utf8(&output.stdout)?;
    // Arch-lint 0.6.0 writes progress messages before its JSON document.
    let start = source.find("\n{").map_or(0, |index| index + 1);
    let report: Value = serde_json::from_str(&source[start..])?;
    if report["files_checked"].as_u64() != Some(u64::try_from(expected_files)?) {
        return Err("Arch-lint did not check every repository Rust source file".into());
    }
    if report["violations"]
        .as_array()
        .is_none_or(|rows| !rows.is_empty())
    {
        return Err("Arch-lint reported an architecture violation".into());
    }
    Ok(())
}
