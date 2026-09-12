use serde::{Deserialize, Serialize};

use crate::{Error, Result};

const TIERS: [&str; 11] = [
    "initiate",
    "seeker",
    "acolyte",
    "sentinel",
    "mystic",
    "ritualist",
    "emissary",
    "oracle",
    "phantom",
    "ascendant",
    "eternus",
];
const DIVISIONS: [&str; 6] = ["i", "ii", "iii", "iv", "v", "vi"];
const DIVISION_NAMES: [&str; 6] = ["one", "two", "three", "four", "five", "six"];

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
#[serde(try_from = "u16", into = "u16")]
pub struct Rank(u16);

impl Rank {
    #[must_use]
    pub const fn badge(self) -> u16 {
        self.0
    }

    #[must_use]
    pub const fn tier(self) -> u16 {
        self.0 / 10
    }

    #[must_use]
    pub fn division_label(self) -> &'static str {
        ["I", "II", "III", "IV", "V", "VI"][usize::from(self.0 % 10 - 1)]
    }

    #[must_use]
    pub fn tier_label(self) -> String {
        let label = TIERS[usize::from(self.tier() - 1)];
        label[..1].to_ascii_uppercase() + &label[1..]
    }

    #[must_use]
    pub fn label(self) -> String {
        format!("{} {}", self.tier_label(), self.division_label())
    }
}

impl TryFrom<u16> for Rank {
    type Error = Error;

    fn try_from(badge: u16) -> Result<Self> {
        if !(1..=11).contains(&(badge / 10)) || !(1..=6).contains(&(badge % 10)) {
            return Err(Error::new(format!("Invalid rank badge: {badge}")));
        }
        Ok(Self(badge))
    }
}

impl From<Rank> for u16 {
    fn from(rank: Rank) -> Self {
        rank.0
    }
}

impl std::str::FromStr for Rank {
    type Err = Error;

    fn from_str(value: &str) -> Result<Self> {
        if let Ok(badge) = value.parse::<u16>() {
            return Self::try_from(badge);
        }
        let normalized = value
            .trim()
            .split(|character: char| character.is_whitespace() || character == '_')
            .filter(|part| !part.is_empty())
            .collect::<Vec<_>>()
            .join("-")
            .to_ascii_lowercase();
        let (tier, division) = normalized
            .rsplit_once('-')
            .ok_or_else(|| Error::new("Rank must include a tier and division"))?;
        let tier = match tier {
            "alchemist" => "acolyte",
            "arcanist" => "sentinel",
            "archon" => "emissary",
            value => value,
        };
        let tier = TIERS
            .iter()
            .position(|candidate| *candidate == tier)
            .ok_or_else(|| Error::new(format!("Unknown rank tier: {tier}")))?;
        let division = match division.parse::<u16>() {
            Ok(number) => number,
            Err(_) => {
                u16::try_from(
                    DIVISIONS
                        .iter()
                        .position(|candidate| *candidate == division)
                        .or_else(|| {
                            DIVISION_NAMES
                                .iter()
                                .position(|candidate| *candidate == division)
                        })
                        .ok_or_else(|| Error::new("Unknown rank division"))?,
                )? + 1
            }
        };
        if !(1..=6).contains(&division) {
            return Err(Error::new("Rank division must be between 1 and 6"));
        }
        Self::try_from((u16::try_from(tier)? + 1) * 10 + division)
    }
}

impl std::fmt::Display for Rank {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let tier = TIERS
            .get(usize::from(self.0 / 10 - 1))
            .ok_or(std::fmt::Error)?;
        let division = DIVISIONS
            .get(usize::from(self.0 % 10 - 1))
            .ok_or(std::fmt::Error)?;
        write!(formatter, "{tier}-{division}")
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RankRange {
    pub minimum: Rank,
    pub maximum: Rank,
}

impl Default for RankRange {
    fn default() -> Self {
        Self {
            minimum: Rank(71),
            maximum: Rank(115),
        }
    }
}

impl RankRange {
    /// # Errors
    /// Returns an error when a rank document omits a valid badge or reverses its bounds.
    pub fn from_document(value: &serde_json::Value) -> Result<Self> {
        let rank = |name: &str| -> Result<Rank> {
            Rank::try_from(u16::try_from(crate::json::integer(
                &value[name],
                "badge_id",
            )?)?)
        };
        Self {
            minimum: rank("minimum")?,
            maximum: rank("maximum")?,
        }
        .validate()
    }

    #[must_use]
    pub fn to_document(self) -> serde_json::Value {
        let rank = |rank: Rank| {
            serde_json::json!({"tier":rank.tier_label().to_uppercase(), "division":rank.division_label(),
            "badge_id":rank.badge(), "label":rank.label()})
        };
        serde_json::json!({"minimum":rank(self.minimum), "maximum":rank(self.maximum), "label":self.label()})
    }

    #[must_use]
    pub fn api_parameters(self) -> serde_json::Map<String, serde_json::Value> {
        serde_json::Map::from_iter([
            ("min_average_badge".to_owned(), self.minimum.badge().into()),
            ("max_average_badge".to_owned(), self.maximum.badge().into()),
        ])
    }

    #[must_use]
    pub fn label(self) -> String {
        if self.minimum == self.maximum {
            self.minimum.label()
        } else {
            format!("{}–{}", self.minimum.label(), self.maximum.label())
        }
    }
    /// # Errors
    /// Returns an error if the minimum rank exceeds the maximum rank.
    pub fn validate(self) -> Result<Self> {
        if self.minimum > self.maximum {
            return Err(Error::new("Minimum rank exceeds maximum rank"));
        }
        Ok(self)
    }
}
