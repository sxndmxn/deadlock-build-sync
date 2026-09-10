"""Fixed discovery limits and random seeds."""

from deadlock_build_sync.build_support import SUPPORT

DISCOVERY_METHODS = ("eclat_pairwise", "grouped_pairwise", "grouped_prefixspan")
LEIDEN_RANDOM_SEEDS = (42, 43, 44)
MINIMUM_CORE_OWNERS = SUPPORT.core_owners
MAXIMUM_CORE_COST = 19200
MAXIMUM_CANDIDATES_PER_SIZE = 50
MINIMUM_EXTENSION_RETENTION = 0.50
MINIMUM_GROUP_JACCARD = 0.70
SCHEMA_VERSION = 1
