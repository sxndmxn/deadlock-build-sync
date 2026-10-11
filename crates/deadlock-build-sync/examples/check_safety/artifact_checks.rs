use std::fs;

use deadlock_data::{Error, Result, atomic_write_json};
use serde_json::json;

#[path = "../../src/artifact_transaction.rs"]
mod artifact_transaction;
use artifact_transaction::ArtifactTransaction;

pub fn check_artifact_recovery() -> Result<()> {
    for phase in ["prepared", "previous_moved", "installed"] {
        check_interrupted_installation(phase)?;
    }
    for installed in [false, true] {
        check_interrupted_creation(installed)?;
    }
    check_artifact_lock()?;
    check_invalid_journal()?;
    check_destination_identity()?;
    check_previous_directory_state()?;
    check_complete_installation()
}

fn check_interrupted_creation(installed: bool) -> Result<()> {
    let root = tempfile::tempdir()?;
    let destination = root.path().join("artifacts");
    let retained = root.path().join(".deadlock-artifacts.reference");
    fs::create_dir(&retained)?;
    fs::create_dir(retained.join("new"))?;
    fs::write(retained.join("new/marker"), b"replacement")?;
    atomic_write_json(
        &root.path().join(".artifacts.transaction.json"),
        &json!({
            "schema_version": 1, "destination": "artifacts",
            "directory": ".deadlock-artifacts.reference", "had_previous": false,
        }),
    )?;
    if installed {
        fs::rename(retained.join("new"), &destination)?;
    }
    ArtifactTransaction::recover(&destination)?;
    if destination.try_exists()? != installed || retained.try_exists()? {
        return Err(Error::new(
            "Artifact recovery failed during initial installation",
        ));
    }
    if installed && fs::read(destination.join("marker"))? != b"replacement" {
        return Err(Error::new(
            "Artifact recovery changed the initial installation",
        ));
    }
    Ok(())
}

fn check_interrupted_installation(phase: &str) -> Result<()> {
    let root = tempfile::tempdir()?;
    let destination = root.path().join("artifacts");
    let retained = root.path().join(".deadlock-artifacts.reference");
    fs::create_dir(&destination)?;
    fs::write(destination.join("marker"), b"previous")?;
    fs::create_dir(&retained)?;
    fs::create_dir(retained.join("new"))?;
    fs::write(retained.join("new/marker"), b"replacement")?;
    atomic_write_json(
        &root.path().join(".artifacts.transaction.json"),
        &json!({
            "schema_version": 1, "destination": "artifacts",
            "directory": ".deadlock-artifacts.reference", "had_previous": true,
        }),
    )?;
    if phase != "prepared" {
        fs::rename(&destination, retained.join("previous"))?;
    }
    if phase == "installed" {
        fs::rename(retained.join("new"), &destination)?;
    }
    ArtifactTransaction::recover(&destination)?;
    let expected = if phase == "installed" {
        b"replacement".as_slice()
    } else {
        b"previous".as_slice()
    };
    if fs::read(destination.join("marker"))? != expected
        || retained.try_exists()?
        || root
            .path()
            .join(".artifacts.transaction.json")
            .try_exists()?
    {
        return Err(Error::new(format!(
            "Artifact recovery failed at phase {phase}"
        )));
    }
    ArtifactTransaction::recover(&destination)
}

fn check_artifact_lock() -> Result<()> {
    let root = tempfile::tempdir()?;
    let destination = root.path().join("artifacts");
    let transaction = ArtifactTransaction::new(&destination)?;
    if ArtifactTransaction::recover(&destination).is_ok() {
        return Err(Error::new(
            "Artifact recovery ignored an active transaction lock",
        ));
    }
    drop(transaction);
    ArtifactTransaction::recover(&destination)
}

fn check_invalid_journal() -> Result<()> {
    let root = tempfile::tempdir()?;
    let destination = root.path().join("artifacts");
    let journal = root.path().join(".artifacts.transaction.json");
    atomic_write_json(
        &journal,
        &json!({
            "schema_version": 1, "destination": "artifacts",
            "directory": "../outside", "had_previous": true,
        }),
    )?;
    if ArtifactTransaction::recover(&destination).is_ok() || !journal.try_exists()? {
        return Err(Error::new(
            "Artifact recovery accepted an invalid directory identity",
        ));
    }
    Ok(())
}

fn check_destination_identity() -> Result<()> {
    let root = tempfile::tempdir()?;
    let name = ".deadlock-artifacts.reference";
    let destination = root.path().join(name);
    fs::create_dir(&destination)?;
    fs::write(destination.join("marker"), b"previous")?;
    atomic_write_json(
        &root.path().join(format!(".{name}.transaction.json")),
        &json!({
            "schema_version": 1, "destination": name,
            "directory": name, "had_previous": true,
        }),
    )?;
    if ArtifactTransaction::recover(&destination).is_ok()
        || fs::read(destination.join("marker"))? != b"previous"
    {
        return Err(Error::new(
            "Artifact recovery accepted the destination as a recovery directory",
        ));
    }
    Ok(())
}

fn check_previous_directory_state() -> Result<()> {
    let root = tempfile::tempdir()?;
    let destination = root.path().join("artifacts");
    let retained = root.path().join(".deadlock-artifacts.reference");
    let previous = retained.join("previous");
    fs::create_dir_all(&previous)?;
    fs::write(previous.join("marker"), b"previous")?;
    let journal = root.path().join(".artifacts.transaction.json");
    atomic_write_json(
        &journal,
        &json!({
            "schema_version": 1, "destination": "artifacts",
            "directory": ".deadlock-artifacts.reference", "had_previous": false,
        }),
    )?;
    if ArtifactTransaction::recover(&destination).is_ok()
        || !journal.try_exists()?
        || fs::read(previous.join("marker"))? != b"previous"
    {
        return Err(Error::new(
            "Artifact recovery removed a previous directory with an invalid journal",
        ));
    }
    Ok(())
}

fn check_complete_installation() -> Result<()> {
    let root = tempfile::tempdir()?;
    let destination = root.path().join("artifacts");
    fs::create_dir(&destination)?;
    fs::write(destination.join("marker"), b"previous")?;
    fs::write(destination.join("obsolete"), b"obsolete")?;
    let transaction = ArtifactTransaction::new(&destination)?;
    fs::write(transaction.staged().join("marker"), b"replacement")?;
    transaction.commit()?;
    if fs::read(destination.join("marker"))? != b"replacement"
        || destination.join("obsolete").try_exists()?
    {
        return Err(Error::new(
            "Artifact installation did not replace the complete directory",
        ));
    }
    Ok(())
}
