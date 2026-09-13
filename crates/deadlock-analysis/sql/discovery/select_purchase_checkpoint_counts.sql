WITH checkpoints AS (
    SELECT
        checkpoints_source.checkpoint_index,
        ($path::UBIGINT[])[checkpoints_source.checkpoint_index] AS previous_item,
        ($path::UBIGINT[])[checkpoints_source.checkpoint_index + 1] AS next_item
    FROM range(len($path::UBIGINT[]) + 1) AS checkpoints_source (checkpoint_index)
),

items AS (
    SELECT unnest($items::UBIGINT[]) AS item_id
),

counts AS (
    SELECT
        i.item_id,
        c.checkpoint_index,
        count(p.match_id) AS buyers,
        count(p.match_id) FILTER (
            WHERE
            (c.checkpoint_index = 0 OR previous_purchase.buy_time < p.buy_time)
            AND (
                c.checkpoint_index = len($path::UBIGINT[])
                OR p.buy_time < next_purchase.buy_time
            )
        ) AS checkpoint_count
    FROM items AS i
    CROSS JOIN checkpoints AS c
    LEFT JOIN _item_pool_purchases AS p ON i.item_id = p.item_id
    LEFT JOIN _item_pool_purchases AS previous_purchase
        ON
            p.match_id = previous_purchase.match_id
            AND p.player_slot = previous_purchase.player_slot
            AND c.previous_item = previous_purchase.item_id
    LEFT JOIN _item_pool_purchases AS next_purchase
        ON
            p.match_id = next_purchase.match_id
            AND p.player_slot = next_purchase.player_slot
            AND c.next_item = next_purchase.item_id
    GROUP BY i.item_id, c.checkpoint_index
)

SELECT
    item_id,
    any_value(buyers) AS buyers,
    list(checkpoint_count ORDER BY checkpoint_index) AS counts_by_checkpoint
FROM counts
GROUP BY item_id
ORDER BY item_id;
