WITH one_per_match AS (
    SELECT * FROM experiment_observations
    QUALIFY row_number() OVER (
        PARTITION BY hero_id, match_id
        ORDER BY hash(match_id, player_slot, buy_time, 20260910), buy_time
    ) = 1
)

SELECT
    hero_id,
    match_id,
    player_slot,
    buy_time,
    net_worth,
    relative_state,
    item_id,
    won
FROM one_per_match
QUALIFY
    row_number() OVER (
        PARTITION BY hero_id
        ORDER BY hash(match_id, hero_id, 20260910), match_id
    ) <= $sample_size
ORDER BY hero_id, match_id;
