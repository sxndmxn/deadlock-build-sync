use std::fs::{self, File, FileType};
use std::path::{Path, PathBuf};

use deadlock_data::{Error, Result, atomic_write_json, read_json, text};
use serde_json::json;

#[derive(Debug)]
pub struct ArtifactTransaction {
    destination: PathBuf,
    temporary: tempfile::TempDir,
    staged: PathBuf,
    lock: File,
}

impl ArtifactTransaction {
    pub fn new(destination: &Path) -> Result<Self> {
        let (parent, name) = artifact_location(destination)?;
        fs::create_dir_all(parent)?;
        let lock = lock_artifact_directory(parent, name)?;
        recover_pending_artifacts(destination)?;
        let temporary = tempfile::Builder::new()
            .prefix(".deadlock-artifacts.")
            .tempdir_in(parent)?;
        let staged = temporary.path().join("new");
        fs::create_dir(&staged)?;
        if file_type(destination)?.is_some_and(|kind| !kind.is_dir()) {
            return Err(Error::new("The artifact destination must be a directory"));
        }
        Ok(Self {
            destination: destination.into(),
            temporary,
            staged,
            lock,
        })
    }

    pub fn staged(&self) -> &Path {
        &self.staged
    }

    pub fn existing_file(&self, name: &str) -> Result<Option<PathBuf>> {
        let path = self.destination.join(name);
        match file_type(&path)? {
            Some(kind) if kind.is_file() => Ok(Some(path)),
            Some(_) => Err(Error::new("The existing artifact must be a regular file")),
            None => Ok(None),
        }
    }

    /// # Errors
    /// Returns an error when recovery files are invalid or the artifact lock is unavailable.
    pub fn recover(destination: &Path) -> Result<()> {
        let (parent, name) = artifact_location(destination)?;
        if !parent.try_exists()? {
            return Ok(());
        }
        let _lock = lock_artifact_directory(parent, name)?;
        recover_pending_artifacts(destination)
    }

    pub fn commit(self) -> Result<()> {
        let previous = self.temporary.path().join("previous");
        let had_previous = file_type(&self.destination)?.is_some();
        if had_previous {
            copy_retained_files(&self.destination, &self.staged)?;
        }
        let (parent, name) = artifact_location(&self.destination)?;
        File::open(self.temporary.path())?.sync_all()?;
        let directory = self
            .temporary
            .path()
            .file_name()
            .and_then(|name| name.to_str())
            .ok_or_else(|| Error::new("Artifact recovery directory has no valid name"))?;
        atomic_write_json(
            &journal_path(parent, name),
            &json!({
                "schema_version": 1, "destination": name, "directory": directory,
                "had_previous": had_previous,
            }),
        )?;
        let retained = self.temporary.keep();
        let install = || -> Result<()> {
            if had_previous {
                fs::rename(&self.destination, &previous)?;
                File::open(&retained)?.sync_all()?;
                File::open(parent)?.sync_all()?;
            }
            fs::rename(&self.staged, &self.destination)?;
            File::open(&retained)?.sync_all()?;
            File::open(parent)?.sync_all()?;
            Ok(())
        };
        if let Err(error) = install() {
            return match recover_pending_artifacts(&self.destination) {
                Ok(()) => Err(error.context("Artifact installation failed. Recovery completed")),
                Err(recovery) => Err(Error::new(format!(
                    "Artifact installation failed: {error}. Recovery failed: {recovery}. Recovery files: {}",
                    retained.display()
                ))),
            };
        }
        recover_pending_artifacts(&self.destination)?;
        self.lock.unlock()?;
        Ok(())
    }
}

fn artifact_location(destination: &Path) -> Result<(&Path, &str)> {
    let parent = destination
        .parent()
        .ok_or_else(|| Error::new("Artifact directory has no parent"))?;
    let name = destination
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| Error::new("Artifact directory has no valid name"))?;
    Ok((parent, name))
}

fn lock_artifact_directory(parent: &Path, name: &str) -> Result<File> {
    let lock = File::options()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(parent.join(format!(".{name}.lock")))?;
    lock.try_lock()
        .map_err(|error| Error::new(format!("Cannot lock the artifact directory: {error}")))?;
    Ok(lock)
}

fn journal_path(parent: &Path, name: &str) -> PathBuf {
    parent.join(format!(".{name}.transaction.json"))
}

fn recover_pending_artifacts(destination: &Path) -> Result<()> {
    let (parent, name) = artifact_location(destination)?;
    let journal = journal_path(parent, name);
    match file_type(&journal)? {
        None => return Ok(()),
        Some(kind) if kind.is_file() => (),
        Some(_) => {
            return Err(Error::new(
                "Artifact recovery journal must be a regular file",
            ));
        }
    }
    let record = read_json(&journal)?;
    let directory = text(&record, "directory")?;
    let had_previous = record["had_previous"]
        .as_bool()
        .ok_or_else(|| Error::new("Artifact recovery journal has no previous-directory state"))?;
    if record["schema_version"] != 1
        || record["destination"] != name
        || directory == name
        || !directory.starts_with(".deadlock-artifacts.")
        || Path::new(directory)
            .file_name()
            .and_then(|name| name.to_str())
            != Some(directory)
    {
        return Err(Error::new(
            "Artifact recovery journal has an invalid identity",
        ));
    }
    let retained = parent.join(directory);
    require_directory_or_missing(&retained)?;
    require_directory_or_missing(destination)?;
    let previous = retained.join("previous");
    require_directory_or_missing(&previous)?;
    if !had_previous && file_type(&previous)?.is_some() {
        return Err(Error::new(
            "Artifact recovery journal contradicts the previous directory",
        ));
    }
    if file_type(destination)?.is_none() && had_previous {
        if file_type(&previous)?.is_none() {
            return Err(Error::new(
                "Previous artifact directory is missing during recovery",
            ));
        }
        fs::rename(&previous, destination)?;
        File::open(&retained)?.sync_all()?;
    }
    File::open(parent)?.sync_all()?;
    fs::remove_file(&journal)?;
    File::open(parent)?.sync_all()?;
    if file_type(&retained)?.is_some() {
        fs::remove_dir_all(&retained)?;
        File::open(parent)?.sync_all()?;
    }
    Ok(())
}

fn require_directory_or_missing(path: &Path) -> Result<()> {
    if file_type(path)?.is_some_and(|kind| !kind.is_dir()) {
        return Err(Error::new("Artifact recovery path must be a directory"));
    }
    Ok(())
}

fn copy_retained_files(source: &Path, destination: &Path) -> Result<()> {
    if !fs::symlink_metadata(source)?.is_dir() {
        return Err(Error::new("The artifact source must be a directory"));
    }
    let mut pending = vec![(source.to_path_buf(), destination.to_path_buf())];
    while let Some((source, destination)) = pending.pop() {
        for entry in fs::read_dir(source)? {
            let entry = entry?;
            let path = entry.path();
            let target = destination.join(entry.file_name());
            let kind = entry.file_type()?;
            if !kind.is_dir() && !kind.is_file() {
                return Err(Error::new(
                    "Artifact directory contains a symbolic link or special file",
                ));
            }
            copy_retained_entry(&path, &target, kind)?;
            if kind.is_dir() {
                pending.push((path, target));
            }
        }
        File::open(destination)?.sync_all()?;
    }
    Ok(())
}

fn copy_retained_entry(source: &Path, destination: &Path, kind: FileType) -> Result<()> {
    if let Some(existing) = file_type(destination)? {
        if existing.is_dir() != kind.is_dir() || existing.is_file() != kind.is_file() {
            return Err(Error::new("Artifact replacement has a file type conflict"));
        }
    } else if kind.is_dir() {
        fs::create_dir(destination)?;
    } else {
        fs::copy(source, destination)?;
        File::open(destination)?.sync_all()?;
    }
    Ok(())
}

fn file_type(path: &Path) -> Result<Option<FileType>> {
    match fs::symlink_metadata(path) {
        Ok(metadata) => Ok(Some(metadata.file_type())),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error.into()),
    }
}
