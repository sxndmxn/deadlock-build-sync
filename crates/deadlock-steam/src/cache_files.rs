use std::fs::File;
use std::io::Read;
use std::path::Path;

use deadlock_data::{Error, Result};

pub fn read_limited(path: &Path, maximum: usize) -> Result<Vec<u8>> {
    let file = File::open(path)?;
    let mut bytes = Vec::new();
    file.take(u64::try_from(maximum)? + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > maximum {
        return Err(Error::new(format!(
            "File {} exceeds the {maximum} byte limit",
            path.display()
        )));
    }
    Ok(bytes)
}

pub fn sync_directory(path: &Path) -> Result<()> {
    File::open(path)?.sync_all()?;
    Ok(())
}
