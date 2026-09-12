use serde::{Deserialize, Serialize};

pub const THREAT_CLASSES: [&str; 8] = [
    "active_slot_burden",
    "ally_protection",
    "bullet_pressure",
    "control",
    "healing",
    "mobility_denial",
    "mobility_escape",
    "spirit_pressure",
];

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Threat {
    ActiveSlotBurden,
    AllyProtection,
    BulletPressure,
    Control,
    Healing,
    MobilityDenial,
    MobilityEscape,
    SpiritPressure,
}

impl Threat {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::ActiveSlotBurden => "active_slot_burden",
            Self::AllyProtection => "ally_protection",
            Self::BulletPressure => "bullet_pressure",
            Self::Control => "control",
            Self::Healing => "healing",
            Self::MobilityDenial => "mobility_denial",
            Self::MobilityEscape => "mobility_escape",
            Self::SpiritPressure => "spirit_pressure",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EnemyScope {
    SameLane,
    WholeEnemyTeam,
}
