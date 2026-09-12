use std::collections::BTreeMap;

use deadlock_data::{Result, count_as_f64, integer, normal_quantile, sha256};
use deadlock_input::ItemGraph;
use serde_json::{Value, json};

use crate::branch_candidates::select_choice_indices;
use crate::branch_cohort::ChoiceCohort;
use crate::contrast_estimation::{ContrastResult, estimate_contrast};
use crate::discovery_admission::discovery_record;
use crate::discovery_models::Nomination;

#[derive(Debug)]
pub struct BranchEvaluator<'a> {
    rows: &'a [Value],
    cache: BTreeMap<(u64, u64, String), std::result::Result<ContrastResult, String>>,
}

impl<'a> BranchEvaluator<'a> {
    pub const fn new(rows: &'a [Value]) -> Self {
        Self {
            rows,
            cache: BTreeMap::new(),
        }
    }

    pub fn evaluate(
        &mut self,
        nominee: &Nomination,
        reviewed: &[Value],
        graph: &ItemGraph,
        family: u64,
    ) -> Result<Value> {
        let mut branches = Vec::new();
        let mut audit = Vec::new();
        let mut choices = BTreeMap::new();
        let critical = normal_quantile(1.0 - 0.025 / count_as_f64(family.max(1))?)?;
        for candidate in validated_candidates(nominee, reviewed)? {
            let item = integer(&candidate, "item_id")?;
            let comparator = integer(&candidate, "comparator_item_id")?;
            let checkpoint = usize::try_from(integer(&candidate, "after_step")?)?;
            let key = (item, checkpoint, comparator);
            if let std::collections::btree_map::Entry::Vacant(entry) = choices.entry(key) {
                let indices =
                    select_choice_indices(self.rows, nominee, item, checkpoint, comparator, graph)?;
                entry.insert(ChoiceCohort::new(self.rows, &indices));
            }
            let selected = choices[&key].select(self.rows, &candidate, graph)?;
            let rows = || selected.iter().map(|index| &self.rows[*index]);
            if !has_fold_support(rows(), item, comparator)? {
                audit.push(rejected(
                    &candidate,
                    "Insufficient support in a temporal fold",
                ));
                continue;
            }
            let identity = selected
                .iter()
                .flat_map(|index| index.to_le_bytes())
                .collect::<Vec<_>>();
            let result = self
                .cache
                .entry((item, comparator, sha256(&identity)))
                .or_insert_with(|| {
                    estimate_contrast(rows(), item, comparator).map_err(|error| error.to_string())
                });
            let mut branch = match result {
                Err(error) => {
                    audit.push(rejected(&candidate, error));
                    continue;
                }
                Ok(ContrastResult::Rejected(balance)) => {
                    let mut record = rejected(
                        &candidate,
                        "Balance check failed. Later outcome diagnostics were not calculated.",
                    );
                    record["balance_screening"] = serde_json::to_value(balance)?;
                    audit.push(record);
                    continue;
                }
                Ok(ContrastResult::Estimated(contrast)) => {
                    let mut lower = f64::INFINITY;
                    let mut width = 0.0_f64;
                    for fold in contrast.fold_diagnostics.values() {
                        let radius = (fold.interval[1] - fold.interval[0]) / 2.0 / 1.96 * critical;
                        lower = lower.min(fold.estimate - radius);
                        width = width.max(2.0 * radius);
                    }
                    let mut evidence = serde_json::to_value(&*contrast)?;
                    evidence["hypotheses"] = family.into();
                    evidence["lower_bound"] = lower.into();
                    evidence["test_evaluated"] = false.into();
                    evidence["gates"] = json!({"support":contrast.admitted,"overlap":contrast.admitted,"balance":contrast.admitted,"uncertainty":width<=0.1,
                        "temporal_stability":contrast.stable,"corrected_outcome":lower>0.0,"legal_path":true,"pre_decision_cohort":true});
                    let mut branch = candidate.clone();
                    branch["support"] = contrast.aggregate.support.into();
                    branch["lower_bound"] = lower.into();
                    branch["evidence"] = evidence;
                    branch["admitted"] = (contrast.admitted && lower > 0.0 && width <= 0.1).into();
                    branch
                }
            };
            audit.push(branch.clone());
            if branch["admitted"] == true {
                if let Some(fields) = branch.as_object_mut() {
                    fields.remove("admitted");
                }
                branches.push(branch);
            }
        }
        Ok(json!({"version":1,"branches":branches,"audit":audit,"test_evaluated":false}))
    }
}

fn validated_candidates(nominee: &Nomination, reviewed: &[Value]) -> Result<Vec<Value>> {
    let mut selected = Vec::new();
    for candidate in &nominee.branch_candidates {
        let mut candidate = candidate.clone();
        if candidate["substitution"].is_object() {
            let identity = &candidate["substitution"]["source_identity_id"];
            let source = reviewed.iter().find(|row| {
                row["identity_id"] == *identity
                    && row["evidence_status"] == "outcome_supported"
                    && row["rejections"].as_array().is_some_and(Vec::is_empty)
            });
            let Some(source) = source else {
                continue;
            };
            candidate["substitution"]["discovery"] = discovery_record(source)?;
        }
        selected.push(candidate);
    }
    Ok(selected)
}

fn has_fold_support<'a>(
    rows: impl Iterator<Item = &'a Value>,
    item: u64,
    comparator: u64,
) -> Result<bool> {
    let mut counts = [[0_u64; 2]; 2];
    for row in rows {
        let period = match deadlock_data::text(row, "fold")? {
            "train" => 0,
            "validation" => 1,
            _ => continue,
        };
        let action = match integer(row, "item_id")? {
            identifier if identifier == item => 0,
            identifier if identifier == comparator => 1,
            _ => continue,
        };
        counts[period][action] += 1;
    }
    Ok(counts.into_iter().flatten().all(|count| count >= 20))
}

fn rejected(candidate: &Value, reason: &str) -> Value {
    let mut record = candidate.clone();
    record["admitted"] = false.into();
    record["reason"] = reason.into();
    record
}
