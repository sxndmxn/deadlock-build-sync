use deadlock_data::{Error, MatchMode, Result, validate_sha256};

#[derive(Clone, Debug)]
pub struct GuideIdentity {
    pub snapshot_id: String,
    pub policy_id: String,
    pub client_version: u64,
    pub match_mode: MatchMode,
    pub rank_identity: String,
    pub projection_fingerprint: String,
}

impl GuideIdentity {
    /// # Errors
    /// Returns an error when a required policy, projection, snapshot, or cohort identity is invalid.
    pub fn validate(&self) -> Result<()> {
        validate_sha256(&self.snapshot_id, "Guide snapshot")?;
        validate_sha256(&self.policy_id, "Guide policy")?;
        validate_sha256(&self.projection_fingerprint, "Guide projection")?;
        if self.client_version == 0 || self.rank_identity.trim().is_empty() {
            return Err(Error::new(
                "Guide requires a positive client version and a rank identity",
            ));
        }
        Ok(())
    }
}
