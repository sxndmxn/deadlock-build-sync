use std::path::PathBuf;

pub const APPLICATION_ID: &str = "1422450";
pub const CACHE_FILENAME: &str = "cached_hero_builds.kv3";
pub const CACHE_RELATIVE_PATH: &str = "remote/cfg/cached_hero_builds.kv3";
/// The Steam Cloud index of the app directory. It records the cache fingerprint.
pub const REMOTE_CACHE_FILENAME: &str = "remotecache.vdf";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CacheLocation {
    pub account_id: u32,
    pub cache_path: PathBuf,
    pub app_directory: PathBuf,
}

impl CacheLocation {
    #[must_use]
    pub fn remote_cache_path(&self) -> PathBuf {
        self.app_directory.join(REMOTE_CACHE_FILENAME)
    }
}

#[derive(Clone, Debug, Default)]
pub struct CacheSearch {
    pub account_id: Option<u32>,
    pub cache_path: Option<PathBuf>,
}
