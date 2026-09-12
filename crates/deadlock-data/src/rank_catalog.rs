use std::collections::BTreeMap;

use serde_json::{Map, Value, json};

use crate::error::{Error, Result};
use crate::json::sha256;
use crate::rank::{Rank, RankRange};

#[derive(Clone, Debug)]
pub struct RankCatalog {
    labels: BTreeMap<u16, String>,
    fingerprint: String,
}

impl RankCatalog {
    /// # Errors
    /// Returns an error when the assets omit a required rank tier or repeat a conflicting label.
    pub fn from_assets(rows: &[Value]) -> Result<Self> {
        let mut labels = BTreeMap::new();
        for row in rows {
            if let (Some(tier), Some(label)) = (row["tier"].as_u64(), row["name"].as_str())
                && !label.trim().is_empty()
            {
                let label = label.trim().to_owned();
                if let Some(previous) = labels.insert(u16::try_from(tier)?, label.clone())
                    && previous != label
                {
                    return Err(Error::new("Rank assets contain conflicting tier labels"));
                }
            }
        }
        if (1..=11).any(|tier| !labels.contains_key(&tier)) {
            return Err(Error::new("Rank assets must contain tiers 1 through 11"));
        }
        let fingerprint = sha256(&serde_json::to_vec(&labels)?);
        Ok(Self {
            labels,
            fingerprint,
        })
    }

    #[must_use]
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }

    #[must_use]
    pub fn label(&self, rank: Rank) -> String {
        let tier = self
            .labels
            .get(&rank.tier())
            .cloned()
            .unwrap_or_else(|| rank.tier_label());
        format!("{tier} {}", rank.division_label())
    }

    /// # Errors
    /// Returns an error when the rank bounds are reversed or absent from the catalog.
    pub fn range_document(&self, ranks: RankRange) -> Result<Map<String, Value>> {
        ranks.validate()?;
        let rank = |rank: Rank| -> Result<Value> {
            let label = self
                .labels
                .get(&rank.tier())
                .ok_or_else(|| Error::new("Rank tier is absent from the pinned catalog"))?;
            Ok(
                json!({"tier":label.to_uppercase(), "division":rank.division_label(), "badge_id":rank.badge(), "label":self.label(rank)}),
            )
        };
        let label = if ranks.minimum == ranks.maximum {
            self.label(ranks.minimum)
        } else {
            format!(
                "{}–{}",
                self.label(ranks.minimum),
                self.label(ranks.maximum)
            )
        };
        Ok(Map::from_iter([
            ("minimum".into(), rank(ranks.minimum)?),
            ("maximum".into(), rank(ranks.maximum)?),
            ("label".into(), label.into()),
            ("labels_sha256".into(), self.fingerprint.clone().into()),
        ]))
    }
}
