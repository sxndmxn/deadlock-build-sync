//! One classification of the `Unpublished` section, shared by the installer and `status`.

use std::collections::BTreeMap;

use deadlock_data::{Error, Result};
use deadlock_guides::ManagedTrailer;

use crate::build_metadata::parse_hero_build_metadata;
use crate::cache_read::{SteamCache, UNPUBLISHED};
use crate::cache_request::BuildKey;
use crate::kv3_value::Kv3Value;

/// One value of the `Unpublished` section.
#[derive(Clone, Debug)]
pub enum ScanEntry {
    /// A build of another author, another tool, or a value that is not a build.
    Unrelated,
    /// A blob that this tool cannot parse. It is user data and stays in place.
    Unreadable,
    /// A build that this tool wrote for the account.
    Managed(ManagedEntry),
}

/// A managed build of the account.
#[derive(Clone, Debug)]
pub struct ManagedEntry {
    pub hero_id: u64,
    pub build_id: Option<u64>,
    /// The trailer with the build path. A build with the legacy marker has none.
    pub trailer: Option<ManagedTrailer>,
}

impl ManagedEntry {
    /// Returns the identity of the build in Steam, when the build has a path.
    #[must_use]
    pub fn key(&self) -> Option<BuildKey> {
        Some(BuildKey {
            hero_id: self.hero_id,
            path_id: self.trailer.as_ref()?.path_id.clone(),
        })
    }
}

/// The classified values of the `Unpublished` section, in section order.
#[derive(Clone, Debug)]
pub struct ManagedScan {
    pub entries: Vec<ScanEntry>,
}

impl ManagedScan {
    /// Classifies every value of the `Unpublished` section.
    ///
    /// # Errors
    /// Returns an error when the section is missing or is not an array.
    pub fn scan(cache: &SteamCache, account_id: u32) -> Result<Self> {
        let values = cache.document().root.field(UNPUBLISHED)?.array()?;
        Ok(Self {
            entries: values
                .iter()
                .map(|value| classify(value, account_id))
                .collect(),
        })
    }

    /// Returns the managed entries with their positions in the section.
    pub fn managed(&self) -> impl Iterator<Item = (usize, &ManagedEntry)> {
        self.entries
            .iter()
            .enumerate()
            .filter_map(|(index, entry)| match entry {
                ScanEntry::Managed(managed) => Some((index, managed)),
                ScanEntry::Unrelated | ScanEntry::Unreadable => None,
            })
    }

    /// Returns the position of each managed build with a path.
    ///
    /// # Errors
    /// Returns an error when two builds share one path.
    pub fn positions(&self) -> Result<BTreeMap<BuildKey, usize>> {
        let mut positions = BTreeMap::new();
        for (index, entry) in self.managed() {
            if let Some(key) = entry.key()
                && positions.insert(key, index).is_some()
            {
                return Err(Error::new(
                    "Steam cache contains duplicate managed build paths",
                ));
            }
        }
        Ok(positions)
    }

    /// Returns the number of blobs that this tool cannot parse.
    #[must_use]
    pub fn unreadable(&self) -> usize {
        self.entries
            .iter()
            .filter(|entry| matches!(entry, ScanEntry::Unreadable))
            .count()
    }

    /// Returns true when the entry is a managed build of one of the heroes.
    #[must_use]
    pub fn is_managed_hero(&self, index: usize, hero_ids: &[u64]) -> bool {
        matches!(
            self.entries.get(index),
            Some(ScanEntry::Managed(managed)) if hero_ids.contains(&managed.hero_id)
        )
    }
}

fn classify(value: &Kv3Value, account_id: u32) -> ScanEntry {
    let Ok(bytes) = value.blob() else {
        return ScanEntry::Unrelated;
    };
    let Ok(metadata) = parse_hero_build_metadata(bytes) else {
        return ScanEntry::Unreadable;
    };
    match metadata.hero_id {
        Some(hero_id) if metadata.is_managed(hero_id, account_id) => {
            ScanEntry::Managed(ManagedEntry {
                hero_id,
                build_id: metadata.build_id,
                trailer: metadata.trailer(),
            })
        }
        _ => ScanEntry::Unrelated,
    }
}
