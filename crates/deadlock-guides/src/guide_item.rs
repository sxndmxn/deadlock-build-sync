use deadlock_data::{Error, Result};
use serde::{Deserialize, Serialize};

use crate::item_evidence::ItemEvidence;
use crate::purchase_windows::PurchaseWindow;

pub const MAX_ITEM_ANNOTATION_BYTES: usize = 240;

#[must_use]
pub fn format_purchase_window(window: &PurchaseWindow) -> String {
    format!(
        "{}–{}k",
        round_thousands(window.bucket_start),
        round_thousands(window.bucket_end)
    )
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct GuideItem {
    pub item_id: u64,
    pub name: String,
    pub tier: u64,
    pub purchase_event_observations: u64,
    pub observed_outcome_rate: f64,
    pub observed_outcome_lower_bound: f64,
    pub relative_purchase_event_volume: f64,
    pub windows: Vec<PurchaseWindow>,
    pub required_flex_slots: Option<u32>,
    pub sell_priority: Option<u32>,
    pub imbue_target_ability_id: Option<u64>,
    pub eligible_player_matches: u64,
    pub adopter_matches: u64,
    pub purchase_adoption: f64,
    pub purchase_events: u64,
    pub median_buy_time_s: Option<f64>,
    pub median_valid_buy_net_worth: Option<f64>,
    pub buy_net_worth_q25: Option<f64>,
    pub buy_net_worth_q75: Option<f64>,
    pub valid_buy_net_worth_share: f64,
    pub imbue_target_ability: Option<String>,
    pub imbue_target_matches: u64,
    pub imbue_observations: u64,
    pub imbue_target_share: f64,
    pub annotation_text: String,
}

impl GuideItem {
    #[must_use]
    pub fn from_evidence(evidence: &ItemEvidence) -> Self {
        let window = evidence.reliable_purchase_window();
        let item = evidence.content();
        Self {
            item_id: item.item_id,
            name: item.item.clone(),
            tier: item.tier,
            purchase_event_observations: item.purchase_events,
            observed_outcome_rate: item.observed_outcome_rate,
            relative_purchase_event_volume: item.selection_adoption,
            eligible_player_matches: item.selection_eligible_player_matches,
            adopter_matches: item.selection_adopter_matches,
            purchase_adoption: item.selection_adoption,
            purchase_events: item.purchase_events,
            median_buy_time_s: item.selection_median_buy_time_s,
            median_valid_buy_net_worth: item.selection_median_valid_buy_net_worth,
            buy_net_worth_q25: window.map(|window| window.0),
            buy_net_worth_q75: window.map(|window| window.1),
            valid_buy_net_worth_share: item.selection_valid_buy_net_worth_share,
            imbue_target_ability_id: item.imbue_target_ability_id,
            imbue_target_ability: item.imbue_target_ability.clone(),
            imbue_target_matches: item.imbue_target_matches,
            imbue_observations: item.imbue_observations,
            imbue_target_share: item.imbue_target_share,
            ..Self::default()
        }
    }

    #[must_use]
    pub fn annotation(&self) -> String {
        if !self.annotation_text.is_empty() {
            return self.annotation_text.clone();
        }
        if self.eligible_player_matches != 0 {
            return self.stat_context();
        }
        let timing = if self.windows.is_empty() {
            "unavailable from aggregate telemetry".into()
        } else {
            self.windows
                .iter()
                .map(|window| {
                    let start = round_thousands(window.bucket_start);
                    let end = round_thousands(window.bucket_end);
                    format!("{start}–{end}k")
                })
                .collect::<Vec<_>>()
                .join(" • ")
        };
        format!(
            "Observed buyer purchase-event NW distribution: {timing}\nRelative event volume {:.1}% | observed outcome rate {:.1}%",
            self.relative_purchase_event_volume * 100.0,
            self.observed_outcome_rate * 100.0
        )
    }

    #[must_use]
    pub fn stat_context(&self) -> String {
        let window = self
            .buy_net_worth_q25
            .zip(self.buy_net_worth_q75)
            .map_or_else(
                || "unavailable".into(),
                |(lower, upper)| {
                    let lower = (lower / 1000.0 + 0.5).floor();
                    let upper = (upper / 1000.0 + 0.5).floor();
                    if lower.total_cmp(&upper).is_eq() {
                        format!("about {lower:.0}k")
                    } else {
                        format!("{lower:.0}k - {upper:.0}k")
                    }
                },
            );
        format!(
            "SOUL WINDOW: {window}\nPR: {:.1}% | WR: {:.1}% | TOTAL GAMES: {}",
            self.purchase_adoption * 100.0,
            self.observed_outcome_rate * 100.0,
            format_integer(i128::from(self.adopter_matches))
        )
    }
}

const fn round_thousands(value: u64) -> u64 {
    let whole = value / 1000;
    let remainder = value % 1000;
    whole
        + if remainder > 500 || (remainder == 500 && whole % 2 == 1) {
            1
        } else {
            0
        }
}

#[must_use]
pub fn format_integer(value: i128) -> String {
    let digits = value.unsigned_abs().to_string();
    let mut result = if value < 0 { "-".into() } else { String::new() };
    for (index, character) in digits.chars().enumerate() {
        if index != 0 && (digits.len() - index).is_multiple_of(3) {
            result.push(',');
        }
        result.push(character);
    }
    result
}

/// # Errors
/// Returns an error when a conditional card has empty, generic, multiline, or excessive text.
pub fn conditional_item_annotation(values: [&str; 5]) -> Result<String> {
    let labels = ["VS", "WHY", "SWAP", "WHEN", "SKIP"];
    let mut lines = Vec::new();
    for (label, value) in labels.iter().zip(values) {
        let value = value.trim();
        if value.is_empty() || value.contains(['\n', '\r']) {
            return Err(Error::new(
                "Conditional annotation requires single-line text",
            ));
        }
        lines.push(format!("{label}: {value}"));
    }
    let annotation = lines.join("\n");
    let normalized = annotation.to_lowercase();
    if [
        "documented mechanic",
        "fits the current fight",
        "observable need",
    ]
    .iter()
    .any(|phrase| normalized.contains(phrase))
    {
        return Err(Error::new("Conditional annotation has a generic trigger"));
    }
    if annotation.len() > MAX_ITEM_ANNOTATION_BYTES {
        return Err(Error::new("Item annotation exceeds 240 UTF-8 bytes"));
    }
    Ok(annotation)
}
