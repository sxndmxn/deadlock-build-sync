"""Classify the main effect using explicit text and material tooltip properties."""

from __future__ import annotations

import re

from experiments.identity_paths.tactics import description_text

# Order specific effects before broad damage/healing terms. Only published base
# descriptions and tooltip effect text are searched, never the raw property bag.
EFFECT_RULES = (
    (
        r"dealing significant weapon damage replenishes",
        "Restore ability charges",
        "You can deal weapon damage to restore ability charges",
    ),
    (
        r"bullets temporarily steal max hp",
        "Health steal from shots",
        "You can keep shooting a hero to steal health",
    ),
    (
        r"light or heavy melee.*spirit",
        "Spirit damage on melee",
        "You can land melee attacks to apply Spirit damage and resistance reduction",
    ),
    (
        r"your melee damage will restore ammo|your next heavy melee",
        "Melee damage",
        "You can land heavy melee attacks",
    ),
    (
        r"(?:when in|when you are in) close range|weapon damage when in close range",
        "Close range weapon damage",
        "You can keep shooting at close range",
    ),
    (
        r"next headshot.*heal\b",
        "Headshot damage",
        "You can land headshots for damage and healing",
    ),
    (
        r"imbue an ability with lifesteal.*additional percentage",
        "Ability echo damage",
        "You can hit enemies with the imbued ability for delayed area damage",
    ),
    (
        r"heals? a target allied|heal an ally",
        "Ally healing",
        "An ally needs healing or help to leave a fight",
    ),
    (
        r"provides move speed and fire rate.*allies",
        "Team support",
        "Nearby allies need movement and fire rate",
    ),
    (
        r"barrier.*can be self.cast",
        "Ally protection",
        "You or an ally need a barrier and help to move",
    ),
    (
        r"spirit resist.*aura on a friendly",
        "Ally protection",
        "You or an ally need protection during a close fight",
    ),
    (
        r"immune to bullets|deflect incoming bullets|grants bullet resist|gain additional bullet resist|whenever you take significant weapon damage",
        "Bullet defense",
        "Incoming bullet damage is the main problem",
    ),
    (
        r"gain additional spirit resist|whenever you take significant spirit damage|next instance of high spirit damage",
        "Spirit defense",
        "Incoming Spirit damage is the main problem",
    ),
    (
        r"temporarily death immune|untargetable and invincible",
        "Survive burst damage",
        "You need time to survive a burst of damage",
    ),
    (
        r"purge all non.ultimate negative|next stun.*automatically cleansed|duration of all negative|suppress negative status",
        "Control protection",
        "Enemy control or debuffs prevent your next action",
    ),
    (
        r"barrier when you are stunned",
        "Control protection",
        "You need a barrier when enemy control hits you",
    ),
    (
        r"parry protects you",
        "Spell parry",
        "You can parry an incoming ability or item effect",
    ),
    (
        r"successful parry against an enemy",
        "Melee parry",
        "You can parry an enemy melee attack",
    ),
    (r"teleport", "Engage or escape", "You need a teleport to reach or leave a target"),
    (
        r"apply a stun|applies a stun|freezing",
        "Hard control",
        "You need to stop an enemy with a stun or freeze",
    ),
    (
        r"curses an enemy|build up to a silence",
        "Silence",
        "You need to stop an enemy from using abilities",
    ),
    (
        r"disarms enemy|silences their movement|prevents stamina usage",
        "Disable enemy movement or weapons",
        "You need to stop enemy movement or weapon use",
    ),
    (
        r"reduce their fire rate|fire rate slowed",
        "Reduce enemy fire rate",
        "You need to reduce incoming bullet fire",
    ),
    (
        r"reduces a random ability cooldown",
        "Cooldowns under Spirit damage",
        "You take repeated Spirit hits while abilities are on cooldown",
    ),
    (
        r"grow larger in size",
        "Close fight durability",
        "You need resistances and melee damage in a close fight",
    ),
    (
        r"reduced healing|healing reduction",
        "Healing reduction",
        "Enemy healing prevents a kill",
    ),
    (
        r"spirit resist.*spirit power|spirit resist of the target|spirit resist reduced",
        "Spirit resistance reduction",
        "Your team needs more Spirit damage against a target",
    ),
    (
        r"bullet (?:and spirit )?resist.*(?:enemies|headshot)|reduces bullet resist on enemies|headshot.*bullet resist|bullets reduce enemy bullet resist",
        "Bullet resistance reduction",
        "Your team needs more bullet damage against a target",
    ),
    (
        r"light or heavy melee.*spirit",
        "Spirit damage on melee",
        "You can land melee attacks to apply Spirit damage and resistance reduction",
    ),
    (r"melee.*heal", "Melee healing", "You can land melee attacks to restore health"),
    (
        r"heavy melee|melee damage will",
        "Melee damage",
        "You can land heavy melee attacks",
    ),
    (
        r"reset the cooldown",
        "Reset abilities",
        "You need to use an ability again before its cooldown ends",
    ),
    (
        r"replenishes a charge",
        "Restore ability charges",
        "You can deal weapon damage to restore ability charges",
    ),
    (
        r"dash.jump.*next ability",
        "Ability boost after movement",
        "You can use an ability after a dash-jump",
    ),
    (
        r"weapon damage per unique hero hit",
        "Weapon damage from abilities",
        "You can hit heroes with the imbued ability before shooting",
    ),
    (r"cooldown", "Ability cooldowns", "You need abilities available more often"),
    (
        r"increase.*(?:range|effect radius)",
        "Ability range",
        "Your ability needs more range or area",
    ),
    (
        r"increase.*duration",
        "Ability duration",
        "Your ability effect needs to last longer",
    ),
    (
        r"imbue an ability with permanent spirit",
        "Spirit power",
        "You need more Spirit power on an ability",
    ),
    (
        r"applying heal.*bonus fire rate",
        "Healing support buffs",
        "You can heal a target before they fight",
    ),
    (
        r"effectiveness of your healing",
        "Healing strength",
        "Your healing needs to restore more health",
    ),
    (
        r"spirit lifesteal",
        "Spirit healing",
        "You need healing while dealing Spirit damage",
    ),
    (
        r"bullet.*heal|headshot.*heal",
        "Healing from shots",
        "You can hit enemies with shots to restore health",
    ),
    (
        r"regeneration|grant regen|stacks to heal|heal and gain",
        "Health recovery",
        "You need to restore health between attacks",
    ),
    (
        r"steal max hp",
        "Health steal from shots",
        "You can keep shooting a hero to steal health",
    ),
    (
        r"bonus souls|hatch the egg|passive soul generation",
        "Soul income",
        "You can meet this item's conditions for extra souls",
    ),
    (r"air jump or air dash", "Stamina movement", "You need more movement actions"),
    (
        r"effect of enemy move speed penalties",
        "Slow resistance",
        "Enemy slows prevent movement",
    ),
    (
        r"movement slow|move speed reduced|slows targets",
        "Slow enemies",
        "You need to slow an enemy to keep them in reach",
    ),
    (
        r"stacking spirit amp|bonus spirit damage|periodically deals spirit damage",
        "Spirit damage",
        "You can apply this item's Spirit damage effect",
    ),
    (
        r"bullets.*shock|bullets will ricochet",
        "Damage to nearby enemies",
        "Enemies are close enough for damage to spread",
    ),
    (
        r"fire a bullet towards any attacker",
        "Return damage",
        "Enemies will trigger the return shot by damaging you",
    ),
    (r"headshot", "Headshot damage", "You can land headshots"),
    (
        r"close range",
        "Close range weapon damage",
        "You can keep shooting at close range",
    ),
    (
        r"weapon damage|fire rate",
        "Weapon damage",
        "You can use the item's trigger to improve weapon damage",
    ),
    (r"gain a barrier", "Barrier", "You need a temporary barrier"),
)

STAT_RULES = (
    (
        ("BonusAbilityCharges", "CooldownBetweenChargeReduction"),
        "Ability charges",
        "You need more uses of a charged ability",
    ),
    (
        ("CooldownReduction", "ItemCooldownReduction"),
        "Ability cooldowns",
        "You need abilities available more often",
    ),
    (
        ("BonusAbilityDurationPercent",),
        "Ability duration",
        "Your ability effect needs to last longer",
    ),
    (
        ("TechRangeMultiplier",),
        "Ability range",
        "Your ability needs more range or area",
    ),
    (
        ("NonPlayerBonusWeaponPower",),
        "NPC farming",
        "You need more weapon damage against NPCs",
    ),
    (("BonusBulletSpeedPercent",), "Bullet speed", "You need faster bullets"),
    (
        ("BonusClipSizePercent",),
        "Magazine capacity",
        "You need more shots before a reload",
    ),
    (
        ("AbilityLifestealPercentHero",),
        "Spirit healing",
        "You need healing while dealing Spirit damage",
    ),
    (
        ("BonusHealthRegen",),
        "Health recovery",
        "You need health recovery between attacks",
    ),
    (("BonusHealth",), "Health", "You need more health"),
    (("BonusSprintSpeed",), "Travel speed", "You need faster travel between fights"),
    (("Stamina",), "Stamina movement", "You need more movement actions"),
    (("TechPower", "TechPowerPercent"), "Spirit power", "You need more Spirit power"),
    (("BonusFireRate",), "Fire rate", "You need to fire more bullets in the same time"),
)


def primary_text(asset: dict) -> str:
    parts = [description_text(asset.get("description"))]
    parts.extend(
        description_text(row.get("loc_string"))
        for section in asset.get("tooltip_sections", [])
        if section.get("section_type") != "innate"
        for row in section.get("section_attributes", [])
        if row.get("loc_string")
    )
    return " ".join(dict.fromkeys(part for part in parts if part)).strip()


def material_stats(asset: dict) -> set[str]:
    keys = {
        key
        for section in asset.get("tooltip_sections", [])
        for row in section.get("section_attributes", [])
        for field in ("important_properties", "elevated_properties")
        for key in row.get(field, [])
    }
    return {
        key
        for key in keys
        if str(asset.get("properties", {}).get(key, {}).get("value", "0"))
        not in {"None", "0", "0.0", "-1", ""}
    }


CONDITION_RULES = (
    (
        r"above 65% health",
        "Your health is above 65%, so the conditional bonus is active",
    ),
    (
        r"apply a stun after 2s.*airborne",
        "You need a delayed stun; airborne targets receive a longer stun",
    ),
    (
        r"damage from your ultimate applies a stun",
        "Your ultimate can hit an enemy to trigger a delayed stun",
    ),
    (r"teleport to an enemy target", "You need to teleport to an enemy target"),
    (r"teleport straight ahead", "You need to teleport forward"),
    (r"assist or kill", "You can gain its bonuses from kills and assists"),
    (
        r"hatch the egg.*as long as you are alive",
        "You can stay alive while holding the egg to earn souls",
    ),
    (
        r"target an enemy npc and consume",
        "An enemy NPC is available to consume for extra souls",
    ),
    (
        r"enemy uses an ability.*consume all stacks",
        "You can store stacks from nearby enemy casts, then heal yourself",
    ),
    (
        r"dealing significant spirit damage.*burn",
        "You can deal enough Spirit damage to trigger the burn and reduce healing",
    ),
    (
        r"suppress negative status effects.*cannot be used while",
        "You can activate it before enemy control prevents item use",
    ),
    (
        r"purge all non.ultimate negative.*cannot be used while",
        "You need to remove debuffs while you can still use items",
    ),
)


def trigger_for(normalized: str, default: str) -> str:
    return next(
        (
            trigger
            for pattern, trigger in CONDITION_RULES
            if re.search(pattern, normalized)
        ),
        default,
    )


def purpose(asset: dict) -> dict:
    text = primary_text(asset)
    normalized = re.sub(r"\s+([,.])", r"\1", text).casefold()
    for pattern, label, trigger in EFFECT_RULES:
        match = re.search(pattern, normalized)
        if match:
            return {
                "purpose": label,
                "triggers": [trigger_for(normalized, trigger)],
                "purpose_evidence": match.group(),
                "purpose_basis": "primary effect text",
            }
    # Stat-only items use explicit elevated/important fields. An unknown effect
    # cannot be replaced by an incidental stat merely because it is present.
    if not text:
        stats = material_stats(asset)
        for keys, label, trigger in STAT_RULES:
            matched = sorted(stats.intersection(keys))
            if matched:
                return {
                    "purpose": label,
                    "triggers": [trigger],
                    "purpose_evidence": ", ".join(matched),
                    "purpose_basis": "material tooltip property",
                }
    return {
        "purpose": "General utility",
        "triggers": [text or "Main effect is unknown; follow the core"],
        "purpose_evidence": text,
        "purpose_basis": "unclassified",
    }
