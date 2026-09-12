use deadlock_data::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum GuardOperator {
    #[serde(rename = "eq")]
    Equals,
    #[serde(rename = "ne")]
    NotEquals,
    #[serde(rename = "gte")]
    AtLeast,
    #[serde(rename = "lte")]
    AtMost,
    #[serde(rename = "contains")]
    Contains,
    #[serde(rename = "exists")]
    Exists,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ObservableType {
    Collection,
    Text,
    Integer,
}

fn observable_type(field: &str) -> Result<ObservableType> {
    match field {
        "enemy.heroes"
        | "enemy.lane_heroes"
        | "enemy.threats"
        | "enemy.items"
        | "ally.heroes"
        | "inventory.items"
        | "inventory.components"
        | "objectives.available"
        | "cooldowns.ready" => Ok(ObservableType::Collection),
        "ally.missing_function"
        | "economy.relative_state"
        | "cohort.match_mode"
        | "epoch.identity" => Ok(ObservableType::Text),
        "inventory.open_slots"
        | "inventory.active_bindings"
        | "inventory.flex_slots"
        | "clock_s"
        | "level"
        | "ability_points"
        | "economy.liquid"
        | "economy.net_worth"
        | "objectives.flex_slots"
        | "cohort.rank_badge" => Ok(ObservableType::Integer),
        _ => Err(Error::new(format!(
            "Guard references unknown observable field: {field}"
        ))),
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Guard {
    pub field: String,
    pub operator: GuardOperator,
    #[serde(default)]
    pub value: Value,
}

impl Guard {
    /// # Errors
    /// Returns an error when the field, operator, or comparison value has an incompatible type.
    pub fn validate(&self) -> Result<()> {
        let expected = observable_type(&self.field)?;
        let valid = match self.operator {
            GuardOperator::Exists => true,
            GuardOperator::Contains => expected == ObservableType::Collection,
            GuardOperator::AtLeast | GuardOperator::AtMost => {
                expected == ObservableType::Integer && integer_value(&self.value).is_some()
            }
            GuardOperator::Equals | GuardOperator::NotEquals => match expected {
                ObservableType::Collection => self.value.is_array(),
                ObservableType::Text => self.value.is_string(),
                ObservableType::Integer => integer_value(&self.value).is_some(),
            },
        };
        if !valid {
            return Err(Error::new(format!(
                "Guard {} has an incompatible operator or value",
                self.field
            )));
        }
        Ok(())
    }

    #[must_use]
    pub fn matches(&self, state: &Map<String, Value>) -> bool {
        let current = state.get(&self.field).unwrap_or(&Value::Null);
        match self.operator {
            GuardOperator::Exists => state.contains_key(&self.field),
            GuardOperator::Equals => current == &self.value,
            GuardOperator::NotEquals => current != &self.value,
            GuardOperator::AtLeast => integer_value(current)
                .zip(integer_value(&self.value))
                .is_some_and(|(current, expected)| current >= expected),
            GuardOperator::AtMost => integer_value(current)
                .zip(integer_value(&self.value))
                .is_some_and(|(current, expected)| current <= expected),
            GuardOperator::Contains => current
                .as_array()
                .is_some_and(|values| values.contains(&self.value)),
        }
    }
}

fn integer_value(value: &Value) -> Option<i128> {
    value
        .as_i64()
        .map(i128::from)
        .or_else(|| value.as_u64().map(i128::from))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum DefaultCondition {
    #[serde(rename = "default")]
    Default,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(untagged)]
pub enum BranchCondition {
    Default(DefaultCondition),
    Guard(Guard),
    All(Vec<Guard>),
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PolicyBranch {
    #[serde(rename = "next")]
    pub next_id: String,
    pub when: BranchCondition,
    #[serde(default)]
    pub priority: Option<i64>,
}

impl PolicyBranch {
    #[must_use]
    pub const fn is_default(&self) -> bool {
        matches!(self.when, BranchCondition::Default(_))
    }

    #[must_use]
    pub fn guards(&self) -> &[Guard] {
        match &self.when {
            BranchCondition::Default(_) => &[],
            BranchCondition::Guard(guard) => std::slice::from_ref(guard),
            BranchCondition::All(guards) => guards,
        }
    }

    /// # Errors
    /// Returns an error when the successor, guard conjunction, or guard type is invalid.
    pub fn validate(&self) -> Result<()> {
        if self.next_id.trim().is_empty()
            || matches!(&self.when, BranchCondition::All(guards) if guards.is_empty())
        {
            return Err(Error::new(
                "Policy branch requires a successor and a guard or explicit default",
            ));
        }
        for guard in self.guards() {
            guard.validate()?;
        }
        Ok(())
    }

    #[must_use]
    pub fn matches(&self, state: &Map<String, Value>) -> bool {
        !self.guards().is_empty() && self.guards().iter().all(|guard| guard.matches(state))
    }
}
