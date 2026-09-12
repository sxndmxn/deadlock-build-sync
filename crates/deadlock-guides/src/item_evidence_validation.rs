use deadlock_data::{Error, Result, count_ratio};

use crate::evidence_values::{add_counts, close};
use crate::item_evidence_content::ItemEvidenceContent;

pub fn validate_item(item: &ItemEvidenceContent) -> Result<()> {
    validate_identity(item)?;
    validate_totals(item)?;
    validate_folds(item)?;
    validate_selection(item)?;
    validate_windows(item)?;
    validate_imbue(item)
}

fn validate_identity(item: &ItemEvidenceContent) -> Result<()> {
    if item.item_id == 0
        || item.item.trim().is_empty()
        || item.slot.trim().is_empty()
        || !(1..=4).contains(&item.tier)
    {
        return Err(Error::new("Item evidence has an invalid identity or tier"));
    }
    Ok(())
}

fn validate_totals(item: &ItemEvidenceContent) -> Result<()> {
    if item.eligible_player_matches == 0
        || item.adopter_matches > item.eligible_player_matches
        || item.purchase_events < item.adopter_matches
        || item.wins > item.adopter_matches
    {
        return Err(Error::new(
            "Item evidence has impossible observation counts",
        ));
    }
    validate_rate(
        item.adoption,
        item.adopter_matches,
        item.eligible_player_matches,
    )?;
    validate_rate(item.observed_outcome_rate, item.wins, item.adopter_matches)?;
    nonnegative(item.median_buy_time_s)?;
    probability(item.valid_buy_net_worth_share)?;
    validate_quantiles(
        item.median_valid_buy_net_worth,
        item.buy_net_worth_q25,
        item.buy_net_worth_q75,
    )
}

fn validate_folds(item: &ItemEvidenceContent) -> Result<()> {
    if item.training_eligible_player_matches == 0 {
        return Err(Error::new(
            "Item evidence requires eligible training matches",
        ));
    }
    for (adopters, eligible, rate) in [
        (
            item.training_adopter_matches,
            item.training_eligible_player_matches,
            item.training_adoption,
        ),
        (
            item.validation_adopter_matches,
            item.validation_eligible_player_matches,
            item.validation_adoption,
        ),
        (
            item.test_adopter_matches,
            item.test_eligible_player_matches,
            item.test_adoption,
        ),
    ] {
        if adopters > eligible {
            return Err(Error::new("Item fold adopters exceed its eligible matches"));
        }
        validate_rate(rate, adopters, eligible)?;
    }
    Ok(())
}

fn validate_selection(item: &ItemEvidenceContent) -> Result<()> {
    if item.selection_eligible_player_matches == 0
        || item.selection_adopter_matches
            != add_counts(
                item.training_adopter_matches,
                item.validation_adopter_matches,
            )?
        || item.selection_eligible_player_matches
            != add_counts(
                item.training_eligible_player_matches,
                item.validation_eligible_player_matches,
            )?
        || item.adopter_matches
            != add_counts(item.selection_adopter_matches, item.test_adopter_matches)?
        || item.eligible_player_matches
            != add_counts(
                item.selection_eligible_player_matches,
                item.test_eligible_player_matches,
            )?
    {
        return Err(Error::new(
            "Item evidence has inconsistent selection counts",
        ));
    }
    validate_rate(
        item.selection_adoption,
        item.selection_adopter_matches,
        item.selection_eligible_player_matches,
    )?;
    if item.selection_median_buy_time_s.is_none() != (item.selection_adopter_matches == 0) {
        return Err(Error::new(
            "Item selection timing is inconsistent with its adopter count",
        ));
    }
    if let Some(time) = item.selection_median_buy_time_s {
        nonnegative(time)?;
    }
    if item.selection_valid_buy_net_worth_observations > item.selection_adopter_matches
        || item.selection_median_valid_buy_net_worth.is_none()
            != (item.selection_valid_buy_net_worth_observations == 0)
    {
        return Err(Error::new(
            "Item selection window is inconsistent with its observation count",
        ));
    }
    validate_rate(
        item.selection_valid_buy_net_worth_share,
        item.selection_valid_buy_net_worth_observations,
        item.selection_adopter_matches,
    )?;
    validate_quantiles(
        item.selection_median_valid_buy_net_worth,
        item.selection_buy_net_worth_q25,
        item.selection_buy_net_worth_q75,
    )
}

fn validate_windows(item: &ItemEvidenceContent) -> Result<()> {
    for (observations, adopters, lower, upper) in [
        (
            item.training_valid_buy_net_worth_observations,
            item.training_adopter_matches,
            item.training_buy_net_worth_q25,
            item.training_buy_net_worth_q75,
        ),
        (
            item.validation_valid_buy_net_worth_observations,
            item.validation_adopter_matches,
            item.validation_buy_net_worth_q25,
            item.validation_buy_net_worth_q75,
        ),
    ] {
        if observations > adopters
            || lower.is_none() != (observations == 0)
            || upper.is_none() != (observations == 0)
        {
            return Err(Error::new(
                "Item fold window has inconsistent observation counts",
            ));
        }
        validate_bounds(lower, upper)?;
    }
    if item.selection_valid_buy_net_worth_observations
        != add_counts(
            item.training_valid_buy_net_worth_observations,
            item.validation_valid_buy_net_worth_observations,
        )?
    {
        return Err(Error::new(
            "Item selection window count differs from its training and validation counts",
        ));
    }
    Ok(())
}

fn validate_imbue(item: &ItemEvidenceContent) -> Result<()> {
    probability(item.imbue_target_share)?;
    let Some(target) = item.imbue_target_ability_id else {
        if item.imbue_target_ability.is_some()
            || item.imbue_target_matches > 0
            || item.imbue_observations > 0
            || item.imbue_target_share > 0.0
        {
            return Err(Error::new("Item has imbue observations without a target"));
        }
        return Ok(());
    };
    if target == 0
        || item
            .imbue_target_ability
            .as_ref()
            .is_none_or(|name| name.trim().is_empty())
        || item.imbue_observations == 0
        || item.imbue_target_matches > item.imbue_observations
        || item.imbue_target_matches < 20
        || item.imbue_target_share <= 0.5
    {
        return Err(Error::new(
            "Item imbue evidence lacks a valid target or sufficient support",
        ));
    }
    validate_rate(
        item.imbue_target_share,
        item.imbue_target_matches,
        item.imbue_observations,
    )
}

fn validate_quantiles(median: Option<f64>, lower: Option<f64>, upper: Option<f64>) -> Result<()> {
    if median.is_none() != lower.is_none() || median.is_none() != upper.is_none() {
        return Err(Error::new(
            "Purchase quantiles must all be present or all be absent",
        ));
    }
    validate_bounds(lower, upper)?;
    if let (Some(median), Some(lower), Some(upper)) = (median, lower, upper) {
        nonnegative(median)?;
        if median < lower || median > upper {
            return Err(Error::new(
                "Purchase median is outside its interquartile range",
            ));
        }
    }
    Ok(())
}

fn validate_bounds(lower: Option<f64>, upper: Option<f64>) -> Result<()> {
    if let Some(lower) = lower {
        nonnegative(lower)?;
    }
    if let Some(upper) = upper {
        nonnegative(upper)?;
    }
    if let (Some(lower), Some(upper)) = (lower, upper)
        && lower > upper
    {
        return Err(Error::new("Purchase window boundaries are reversed"));
    }
    Ok(())
}

fn validate_rate(rate: f64, numerator: u64, denominator: u64) -> Result<()> {
    probability(rate)?;
    if !close(rate, count_ratio(numerator, denominator)?, 1.0e-9) {
        return Err(Error::new(
            "Item evidence rate is inconsistent with its counts",
        ));
    }
    Ok(())
}

fn probability(value: f64) -> Result<()> {
    if !value.is_finite() || !(0.0..=1.0).contains(&value) {
        return Err(Error::new("Item probability must be between zero and one"));
    }
    Ok(())
}

fn nonnegative(value: f64) -> Result<()> {
    if !value.is_finite() || value < 0.0 {
        return Err(Error::new(
            "Item measurement must be finite and nonnegative",
        ));
    }
    Ok(())
}
