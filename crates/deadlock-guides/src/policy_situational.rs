use std::collections::BTreeMap;

use deadlock_data::{Error, Result};
use serde_json::Value;

use crate::guide_item::conditional_item_annotation;
use crate::mechanic_decisions::conditional_item_decision;
use crate::mechanic_responses::classify_item_threat_responses;
use crate::policy_cards::CounterCard;
use crate::policy_claim::EvidenceClaim;
use crate::policy_claim_generation::ClaimContext;
use crate::policy_guard::{BranchCondition, Guard, GuardOperator, PolicyBranch};
use crate::policy_node::{NodeKind, PolicyNode};
use crate::situational_branch::SituationalBranchContent;
use crate::threat::{EnemyScope, Threat};

pub struct SituationalPolicyEntry {
    pub comparator_id: u64,
    pub branch: PolicyBranch,
    pub purchase: PolicyNode,
    pub card: CounterCard,
    pub claim: EvidenceClaim,
}

pub fn build_situational_entry(
    position: usize,
    hero_id: u64,
    source: &SituationalBranchContent,
    assets: &BTreeMap<u64, &Value>,
    context: &ClaimContext<'_>,
) -> Result<SituationalPolicyEntry> {
    let item = require_asset(assets, source.item_id)?;
    let comparator = require_asset(assets, source.comparator_item_id)?;
    let response = source.mechanic_ref.rsplit('/').next().unwrap_or_default();
    if response_threat(response) != Some(source.threat)
        || !classify_item_threat_responses(item)?.contains(response)
    {
        return Err(Error::new(format!(
            "Situational item {} lacks its stated response mechanic",
            source.item_id
        )));
    }
    let claim = context.situational_claim(hero_id, source);
    let purchase_id = format!("situational-{position}");
    let purchase = PolicyNode {
        node_id: purchase_id.clone(),
        kind: NodeKind::Purchase,
        next_id: Some("end".into()),
        evidence_ref: Some(claim.claim_id.clone()),
        item_id: Some(source.item_id),
        optional: true,
        annotation: situational_annotation(item, comparator, response)?,
        ..PolicyNode::default()
    };
    let branch = PolicyBranch {
        next_id: purchase_id,
        when: BranchCondition::All(situational_guards(source)),
        priority: None,
    };
    let card = CounterCard {
        threat: source.threat.as_str().into(),
        item_id: source.item_id,
        comparator_item_id: source.comparator_item_id,
        mechanic_ref: source.mechanic_ref.clone(),
        legal_timing: "same observed decision opportunity".into(),
        alternative: source.comparator.clone(),
        replacement: source.replacement.clone(),
        execution_mode: source.execution.clone(),
        failure_condition: source.failure_condition.clone(),
        evidence_ref: claim.claim_id.clone(),
        enemy_hero_id: source.enemy_hero_id,
        enemy_scope: match source.enemy_scope {
            EnemyScope::SameLane => "same_lane",
            EnemyScope::WholeEnemyTeam => "whole_enemy_team",
        }
        .into(),
        phase: source.phase,
        tier: source.tier,
        enemy_mechanics_refs: source.enemy_mechanics_refs.clone(),
    };
    Ok(SituationalPolicyEntry {
        comparator_id: source.comparator_item_id,
        branch,
        purchase,
        card,
        claim,
    })
}

fn require_asset<'asset>(assets: &BTreeMap<u64, &'asset Value>, id: u64) -> Result<&'asset Value> {
    assets
        .get(&id)
        .copied()
        .ok_or_else(|| Error::new(format!("Situational branch references absent asset {id}")))
}

fn response_threat(response: &str) -> Option<Threat> {
    Some(match response {
        "hard_control" => Threat::Control,
        "healing" => Threat::Healing,
        "bullet_pressure" => Threat::BulletPressure,
        "spirit_burst" => Threat::SpiritPressure,
        "mobility_denial" => Threat::MobilityEscape,
        "slow_resistance" => Threat::MobilityDenial,
        "ally_protection" => Threat::AllyProtection,
        _ => return None,
    })
}

fn situational_guards(source: &SituationalBranchContent) -> Vec<Guard> {
    let mut guards = vec![Guard {
        field: "enemy.threats".into(),
        operator: GuardOperator::Contains,
        value: source.threat.as_str().into(),
    }];
    if let Some(id) = source.enemy_hero_id {
        let field = match source.enemy_scope {
            EnemyScope::SameLane => "enemy.lane_heroes",
            EnemyScope::WholeEnemyTeam => "enemy.heroes",
        };
        guards.push(Guard {
            field: field.into(),
            operator: GuardOperator::Contains,
            value: id.into(),
        });
    }
    let (earliest, latest) = match source.phase {
        0 => (0, Some(539)),
        1 => (540, Some(1199)),
        2 => (1200, Some(1799)),
        _ => (1800, None),
    };
    guards.push(Guard {
        field: "clock_s".into(),
        operator: GuardOperator::AtLeast,
        value: earliest.into(),
    });
    if let Some(latest) = latest {
        guards.push(Guard {
            field: "clock_s".into(),
            operator: GuardOperator::AtMost,
            value: latest.into(),
        });
    }
    guards
}

fn situational_annotation(item: &Value, comparator: &Value, response: &str) -> Result<String> {
    let decision = conditional_item_decision(item, comparator, Some(response))?
        .ok_or_else(|| Error::new("Situational item has no supported decision text"))?;
    let name = comparator["name"]
        .as_str()
        .filter(|name| !name.is_empty())
        .map_or_else(|| format!("item {}", comparator["id"]), str::to_owned);
    conditional_item_annotation([
        &decision.vs,
        &decision.why,
        &format!("Replaces {name}"),
        &decision.when,
        &decision.skip,
    ])
}
