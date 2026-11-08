use serde::{Deserialize, Serialize};
use serde_json::json;

use crate::error::{Error, Result};
use crate::json::{fingerprint, validate_sha256};

/// The game update that starts a match window, from the Steam news feed or the forum.
///
/// The identity is the fingerprint of the source fields. Two catalogs with the same identity
/// come from the same patch post with the same content.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Patch {
    pub identity: String,
    pub title: String,
    pub start_timestamp: i64,
    pub published_at: String,
    pub source: String,
    pub guid: String,
    pub link: String,
    pub content_sha256: String,
}

/// The source fields of a patch post.
#[derive(Clone, Debug)]
pub struct PatchPost {
    pub title: String,
    pub start_timestamp: i64,
    pub published_at: String,
    pub source: String,
    pub guid: String,
    pub link: String,
    pub content_sha256: String,
}

impl Patch {
    /// Builds a patch with the identity of its post.
    ///
    /// # Errors
    /// Returns an error when the post has an empty title, source, or GUID, or an invalid content hash.
    pub fn from_post(post: PatchPost) -> Result<Self> {
        let patch = Self {
            identity: identity_of(&post)?,
            title: post.title.trim().to_owned(),
            start_timestamp: post.start_timestamp,
            published_at: post.published_at,
            source: post.source,
            guid: post.guid,
            link: post.link,
            content_sha256: post.content_sha256,
        };
        patch.validate()?;
        Ok(patch)
    }

    /// # Errors
    /// Returns an error when a field is empty or the identity does not match the fields.
    pub fn validate(&self) -> Result<()> {
        if self.title.trim().is_empty() || self.source.trim().is_empty() || self.guid.is_empty() {
            return Err(Error::new("Patch requires a title, a source, and a GUID"));
        }
        validate_sha256(&self.content_sha256, "patch content")?;
        let expected = identity_of(&PatchPost {
            title: self.title.clone(),
            start_timestamp: self.start_timestamp,
            published_at: self.published_at.clone(),
            source: self.source.clone(),
            guid: self.guid.clone(),
            link: self.link.clone(),
            content_sha256: self.content_sha256.clone(),
        })?;
        if self.identity != expected {
            return Err(Error::new("Patch identity does not match its fields"));
        }
        Ok(())
    }
}

fn identity_of(post: &PatchPost) -> Result<String> {
    fingerprint(&json!({
        "source": post.source,
        "guid": post.guid,
        "published_at": post.published_at,
        "link": post.link,
        "content_sha256": post.content_sha256,
    }))
}
