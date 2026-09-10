"""Fixed support and stability limits for core policy analysis."""

MINIMUM_SUPPORT = 20
MINIMUM_OVERLAP = 0.50
MAXIMUM_STANDARDIZED_MEAN_DIFFERENCE = 0.10
MAXIMUM_INTERVAL_WIDTH = 0.10
MINIMUM_EFFECTIVE_SUPPORT = 20.0
PROPENSITY_FLOOR = 0.05
WEIGHT_CLIP_LIMITS = (5.0, 10.0, 20.0)
SELECTION_FOLDS = ("train", "validation")

STATE_FEATURES = (
    "average_badge",
    "phase",
    "buy_time",
    "own_net_worth_at_buy",
    "state_observed_at_s",
    "own_team_net_worth",
    "enemy_team_net_worth",
    "team_net_worth_lead",
    "state_age_s",
    "prior_catalog_spend",
    "prior_purchase_count",
)
