use deadlock_data::{Error, Result, count_as_f64};
use num_traits::ToPrimitive as _;

pub fn quantiles(values: &mut [f64]) -> Result<Option<[f64; 3]>> {
    if values.is_empty() {
        return Ok(None);
    }
    if values.iter().any(|value| !value.is_finite()) {
        return Err(Error::new("Quantile sample contains a nonfinite value"));
    }
    values.sort_by(f64::total_cmp);
    let last = count_as_f64(u64::try_from(values.len() - 1)?)?;
    let mut result = [0.0; 3];
    for (index, share) in [0.25, 0.5, 0.75].into_iter().enumerate() {
        let position = last * share;
        let left = position
            .floor()
            .to_usize()
            .ok_or_else(|| Error::new("Quantile position exceeds the index range"))?;
        let right = position
            .ceil()
            .to_usize()
            .ok_or_else(|| Error::new("Quantile position exceeds the index range"))?;
        let fraction = position - position.floor();
        let difference = values[right] - values[left];
        result[index] = if fraction < 0.5 {
            difference.mul_add(fraction, values[left])
        } else {
            difference.mul_add(-(1.0 - fraction), values[right])
        };
    }
    Ok(Some(result))
}
