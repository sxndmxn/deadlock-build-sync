"""Fixed limits from the accepted experiment protocol."""

from deadlock_build_sync.build_support import SUPPORT

ARMS = ("eclat_pairwise", "grouped_pairwise", "grouped_prefixspan")
SEEDS = (42, 43, 44)
MINIMUM = SUPPORT.core_owners
MAXIMUM_COST = 19200
PER_SIZE = 50
EXTENSION_RETENTION = 0.50
GROUP_JACCARD = 0.70
SCHEMA_VERSION = 1
