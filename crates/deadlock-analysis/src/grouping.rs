use deadlock_data::{Error, Result, count_as_f64, count_ratio};
use leiden_rs::{GraphDataBuilder, Leiden, LeidenConfig, QualityType};
use serde_json::{Value, json};

use crate::discovery_data::DiscoveryData;
use crate::mining::Candidate;

pub fn group_candidates(candidates: &[Candidate], data: &DiscoveryData) -> Result<Value> {
    let weights = ownership_similarities(candidates, data)?;
    group_weights(candidates, &weights, true)
}

pub fn group_item_candidates(candidates: &[Candidate]) -> Result<Value> {
    let mut weights = vec![vec![0.0; candidates.len()]; candidates.len()];
    for first in 0..candidates.len() {
        weights[first][first] = 1.0;
        for second in first + 1..candidates.len() {
            let shared = candidates[first]
                .items
                .iter()
                .filter(|item| candidates[second].items.contains(item))
                .count();
            let union = candidates[first].items.len() + candidates[second].items.len() - shared;
            let score = count_ratio(u64::try_from(shared)?, u64::try_from(union.max(1))?)?;
            if shared >= 2 && score >= 0.5 {
                weights[first][second] = score;
                weights[second][first] = score;
            }
        }
    }
    group_weights(candidates, &weights, false)
}

fn group_weights(
    candidates: &[Candidate],
    weights: &[Vec<f64>],
    positive_edges: bool,
) -> Result<Value> {
    let size = candidates.len();
    let mut builder = GraphDataBuilder::new(size);
    let mut edges = Vec::new();
    for (first, row) in weights.iter().enumerate() {
        for (second, weight) in row.iter().enumerate().skip(first + 1) {
            if *weight > 0.0 {
                builder
                    .add_edge(first, second, *weight)
                    .map_err(|error| grouping_error(&error))?;
                edges.push((first, second));
            }
        }
    }
    let graph = builder.build().map_err(|error| grouping_error(&error))?;
    let mut assignments = Vec::new();
    let mut votes = vec![vec![0_u8; size]; size];
    for seed in [42, 43, 44] {
        let membership = if edges.is_empty() {
            (0..size).collect::<Vec<_>>()
        } else {
            Leiden::new(LeidenConfig {
                max_iterations: 10,
                min_iterations: 10,
                quality: QualityType::RBConfiguration,
                resolution: 1.0,
                seed: Some(seed),
                ..LeidenConfig::default()
            })
            .run(&graph)
            .map_err(|error| grouping_error(&error))?
            .partition
            .as_slice()
            .to_vec()
        };
        for first in 0..size {
            for second in 0..size {
                votes[first][second] += u8::from(membership[first] == membership[second]);
            }
        }
        assignments.push(json!({"seed":seed,"membership":membership}));
    }
    let groups = merge_groups(weights, &votes, positive_edges)?;
    Ok(
        json!({"groups":groups,"seeds":assignments,"edges":edges.iter().map(|(first,second)|json!({"first":first,"second":second,"jaccard":weights[*first][*second],"votes":votes[*first][*second]})).collect::<Vec<_>>(),
        "candidate_order":candidates.iter().map(|candidate|&candidate.items).collect::<Vec<_>>()}),
    )
}

fn ownership_similarities(candidates: &[Candidate], data: &DiscoveryData) -> Result<Vec<Vec<f64>>> {
    let masks = candidates
        .iter()
        .map(|candidate| {
            let columns = data.columns(&candidate.items)?;
            Ok(data
                .fold_rows("discovery")
                .map(|row| data.owns(row, &columns))
                .collect::<Vec<_>>())
        })
        .collect::<Result<Vec<_>>>()?;
    let mut weights = vec![vec![0.0; candidates.len()]; candidates.len()];
    for first in 0..candidates.len() {
        weights[first][first] = 1.0;
        for second in first + 1..candidates.len() {
            if candidates[first]
                .items
                .iter()
                .filter(|item| candidates[second].items.contains(item))
                .count()
                < 2
            {
                continue;
            }
            let intersection = masks[first]
                .iter()
                .zip(&masks[second])
                .filter(|(left, right)| **left && **right)
                .count();
            let union = masks[first]
                .iter()
                .zip(&masks[second])
                .filter(|(left, right)| **left || **right)
                .count();
            let weight = count_ratio(u64::try_from(intersection)?, u64::try_from(union.max(1))?)?;
            if weight >= 0.7 {
                weights[first][second] = weight;
                weights[second][first] = weight;
            }
        }
    }
    Ok(weights)
}

fn merge_groups(
    weights: &[Vec<f64>],
    votes: &[Vec<u8>],
    positive_edges: bool,
) -> Result<Vec<Vec<usize>>> {
    let mut groups = (0..weights.len())
        .map(|index| vec![index])
        .collect::<Vec<_>>();
    loop {
        let mut choices = Vec::new();
        for first in 0..groups.len() {
            for second in first + 1..groups.len() {
                let pairs = groups[first]
                    .iter()
                    .flat_map(|left| groups[second].iter().map(move |right| (*left, *right)))
                    .collect::<Vec<_>>();
                if !pairs.iter().all(|(left, right)| {
                    votes[*left][*right] >= 2 && (!positive_edges || weights[*left][*right] > 0.0)
                }) {
                    continue;
                }
                let mean = pairs
                    .iter()
                    .map(|(left, right)| weights[*left][*right])
                    .sum::<f64>()
                    / count_as_f64(u64::try_from(pairs.len())?)?;
                let mut merged = groups[first]
                    .iter()
                    .chain(&groups[second])
                    .copied()
                    .collect::<Vec<_>>();
                merged.sort_unstable();
                choices.push((mean, merged, first, second));
            }
        }
        choices.sort_by(|left, right| {
            right
                .0
                .total_cmp(&left.0)
                .then_with(|| left.1.cmp(&right.1))
                .then(left.2.cmp(&right.2))
                .then(left.3.cmp(&right.3))
        });
        let Some((_, merged, first, second)) = choices.into_iter().next() else {
            return Ok(groups);
        };
        groups.remove(second);
        groups.remove(first);
        groups.push(merged);
        groups.sort();
    }
}

fn grouping_error(error: &leiden_rs::error::LeidenError) -> Error {
    Error::new(format!("Core grouping failed: {error}"))
}
