use std::collections::BTreeMap;

use deadlock_data::{Error, Result, count_as_f64, count_ratio};
use serde_json::{Value, json};
use statrs::distribution::{Binomial, ContinuousCDF as _, DiscreteCDF as _, Normal};

use crate::discovery_data::DiscoveryData;

#[derive(Clone, Copy, Debug, Default)]
struct OutcomeCell {
    counts: [u64; 2],
    wins: [u64; 2],
}

pub fn evaluate_core(data: &DiscoveryData, items: &[u64], fold: &str) -> Result<Value> {
    let columns = data.columns(items)?;
    let rows = data.fold_rows(fold).collect::<Vec<_>>();
    let owners = rows
        .iter()
        .filter(|row| data.owns(**row, &columns))
        .copied()
        .collect::<Vec<_>>();
    let count = u64::try_from(owners.len())?;
    let wins = u64::try_from(owners.iter().filter(|row| data.rows[**row].won).count())?;
    let population = u64::try_from(rows.len())?;
    let hero_wins = u64::try_from(rows.iter().filter(|row| data.rows[**row].won).count())?;
    let expected = columns
        .iter()
        .map(|column| {
            count_ratio(
                u64::try_from(
                    rows.iter()
                        .filter(|row| data.times[**row][*column] >= 0)
                        .count(),
                )?,
                population.max(1),
            )
        })
        .collect::<Result<Vec<_>>>()?
        .iter()
        .product::<f64>();
    let mut adjusted = standardized_difference(data, &rows, &columns)?;
    adjusted["overlap_share"] = count_ratio(
        deadlock_data::integer(&adjusted, "core_overlap")?,
        count.max(1),
    )?
    .into();
    let win_p = if wins == 0 {
        1.0
    } else {
        Binomial::new(0.5, count)
            .map_err(|error| Error::new(error.to_string()))?
            .sf(wins - 1)
    };
    Ok(
        json!({"fold":fold,"rows":population,"owners":count,"wins":wins,
        "win_rate":if count == 0 {None} else {Some(count_ratio(wins,count)?)},
        "hero_win_rate":if population == 0 {None} else {Some(count_ratio(hero_wins,population)?)},
        "coverage":count_ratio(count,population.max(1))?,
        "joint_lift":if expected > 0.0 { count_ratio(count,population.max(1))? / expected } else {0.0},
        "win_lower_95":wilson_lower(wins,count)?,"win_p_greater_half":win_p,"adjusted":adjusted}),
    )
}

fn standardized_difference(
    data: &DiscoveryData,
    rows: &[usize],
    columns: &[usize],
) -> Result<Value> {
    let mut cells = BTreeMap::<(u64, usize, u16), OutcomeCell>::new();
    for index in rows {
        let row = &data.rows[*index];
        if let (Some(wealth), Some(lead)) = (row.observed_wealth, row.team_lead)
            && wealth.is_finite()
            && lead.is_finite()
        {
            let key = (
                (wealth / 5000.0).floor().to_bits(),
                [-0.1, -0.03, 0.03, 0.1].partition_point(|boundary| lead >= *boundary),
                row.average_badge / 20,
            );
            let owned = usize::from(data.owns(*index, columns));
            let cell = cells.entry(key).or_default();
            cell.counts[owned] += 1;
            cell.wins[owned] += u64::from(row.won);
        }
    }
    let common = cells
        .values()
        .filter(|cell| cell.counts.iter().all(|count| *count >= 10))
        .collect::<Vec<_>>();
    let overlap = common.iter().map(|cell| cell.counts[1]).sum::<u64>();
    let mut result = json!({"core_overlap":overlap,"overlap_share":0.0,"strata":common.len(),"difference":null,"lower_95":null,"p_greater":1.0});
    if overlap < 100 {
        return Ok(result);
    }
    let mut adjusted = [0.0; 2];
    let mut variance = 0.0;
    for cell in common {
        let weight = count_ratio(cell.counts[1], overlap)?;
        for (index, adjusted) in adjusted.iter_mut().enumerate() {
            let count = count_as_f64(cell.counts[index])?;
            let wins = count_as_f64(cell.wins[index])?;
            *adjusted += weight * wins / count;
            let smoothed = (wins + 0.5) / (count + 1.0);
            variance += weight.powi(2) * smoothed * (1.0 - smoothed) / count;
        }
    }
    let difference = adjusted[1] - adjusted[0];
    let error = variance.sqrt();
    for (name, value) in [
        ("difference", difference),
        ("standard_error", error),
        ("lower_95", 1.96f64.mul_add(-error, difference)),
        ("core_rate", adjusted[1]),
        ("noncore_rate", adjusted[0]),
        ("p_greater", normal_survival(difference / error.max(1e-15))?),
    ] {
        result[name] = value.into();
    }
    Ok(result)
}

fn wilson_lower(wins: u64, count: u64) -> Result<f64> {
    if count == 0 {
        return Ok(0.0);
    }
    let rate = count_ratio(wins, count)?;
    let count = count_as_f64(count)?;
    let z = 1.96_f64;
    Ok(z.mul_add(
        -(rate * (1.0 - rate) / count + z.powi(2) / (4.0 * count.powi(2))).sqrt(),
        rate + z.powi(2) / (2.0 * count),
    ) / (1.0 + z.powi(2) / count))
}

pub fn normal_survival(value: f64) -> Result<f64> {
    Ok(Normal::new(0.0, 1.0)
        .map_err(|error| Error::new(error.to_string()))?
        .sf(value))
}
