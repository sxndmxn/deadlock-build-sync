use std::fs::{self, File, FileType};
use std::path::{Path, PathBuf};

use deadlock_data::{Error, Result};

#[derive(Debug)]
pub struct ArtifactTransaction {
    destination: PathBuf,
    temporary: tempfile::TempDir,
    staged: PathBuf,
    lock: File,
}

impl ArtifactTransaction {
    pub fn new(destination: &Path) -> Result<Self> {
        let parent = destination
            .parent()
            .ok_or_else(|| Error::new("Artifact directory has no parent"))?;
        let name = destination
            .file_name()
            .and_then(|name| name.to_str())
            .ok_or_else(|| Error::new("Artifact directory has no valid name"))?;
        fs::create_dir_all(parent)?;
        let lock = File::options()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(parent.join(format!(".{name}.lock")))?;
        lock.try_lock()
            .map_err(|error| Error::new(format!("Cannot lock the artifact directory: {error}")))?;
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

    pub fn commit(self) -> Result<()> {
        let previous = self.temporary.path().join("previous");
        let had_previous = file_type(&self.destination)?.is_some();
        if had_previous {
            copy_retained_files(&self.destination, &self.staged)?;
            fs::rename(&self.destination, &previous)?;
        }
        if let Err(error) = fs::rename(&self.staged, &self.destination) {
            if had_previous && let Err(recovery) = fs::rename(&previous, &self.destination) {
                let retained = self.temporary.keep();
                return Err(Error::new(format!(
                    "Artifact installation failed: {error}. Recovery failed: {recovery}. Previous artifacts remain at {}",
                    retained.join("previous").display()
                )));
            }
            return Err(Error::new(format!(
                "Artifact installation failed: {error}. The previous artifacts remain intact"
            )));
        }
        let parent = self
            .destination
            .parent()
            .ok_or_else(|| Error::new("Artifact directory has no parent"))?;
        if let Err(error) = File::open(parent).and_then(|file| file.sync_all()) {
            let retained = self.temporary.keep();
            return Err(Error::new(format!(
                "Artifact directory synchronization failed: {error}. Recovery files remain at {}",
                retained.display()
            )));
        }
        self.temporary.close()?;
        self.lock.unlock()?;
        Ok(())
    }
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
