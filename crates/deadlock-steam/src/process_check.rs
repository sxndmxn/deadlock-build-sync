use std::fs;
use std::io::ErrorKind;
use std::path::Path;

use deadlock_data::{Error, Result};

use crate::cache_files::read_limited;

pub trait ProcessInspection {
    /// # Errors
    /// Returns an error when Deadlock is running or its process state is unknown.
    fn require_stopped(&self) -> Result<()>;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct LinuxProcesses;

impl ProcessInspection for LinuxProcesses {
    fn require_stopped(&self) -> Result<()> {
        require_deadlock_stopped()
    }
}

/// # Errors
/// Returns an error when process inspection fails or Deadlock is running.
pub fn require_deadlock_stopped() -> Result<()> {
    check_process_directory(Path::new("/proc"))
}

fn check_process_directory(root: &Path) -> Result<()> {
    let entries = fs::read_dir(root)
        .map_err(|error| Error::new(format!("Cannot check running processes: {error}")))?;
    for entry in entries {
        let entry = entry?;
        if entry
            .file_name()
            .to_str()
            .is_some_and(|name| !name.is_empty() && name.bytes().all(|byte| byte.is_ascii_digit()))
        {
            check_command(&entry.path().join("cmdline"))?;
        }
    }
    Ok(())
}

fn check_command(path: &Path) -> Result<()> {
    match fs::metadata(path) {
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error.into()),
        Ok(_) => (),
    }
    let command = match read_limited(path, 1024 * 1024) {
        Ok(bytes) => bytes,
        Err(_) if !path.try_exists()? => return Ok(()),
        Err(error) => return Err(error.context("Cannot inspect a running process")),
    };
    if command.split(|byte| *byte == 0).any(is_deadlock_argument) {
        return Err(Error::new(
            "Deadlock is running. Close Deadlock before you change the Steam cache",
        ));
    }
    Ok(())
}

fn is_deadlock_argument(argument: &[u8]) -> bool {
    let argument = String::from_utf8_lossy(argument);
    let name = argument
        .trim_matches('"')
        .rsplit(['/', '\\'])
        .next()
        .unwrap_or_default();
    name.eq_ignore_ascii_case("deadlock.exe") || name.eq_ignore_ascii_case("deadlock")
}
