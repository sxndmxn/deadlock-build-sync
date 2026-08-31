ITEM_OUTCOME_AGGREGATES_SQL = """
sum(p.won::INTEGER) AS wins,
avg(p.won::INTEGER) AS raw_outcome_rate,
median(p.buy_time) AS median_buy_time_s,
quantile_cont(p.buy_time, 0.25) AS buy_time_q25_s,
quantile_cont(p.buy_time, 0.75) AS buy_time_q75_s,
median(p.own_net_worth_at_buy) AS median_valid_buy_net_worth,
quantile_cont(p.own_net_worth_at_buy, 0.25) AS buy_nw_q25,
quantile_cont(p.own_net_worth_at_buy, 0.75) AS buy_nw_q75,
count(p.own_net_worth_at_buy) / count(*) AS valid_buy_nw_share
""".strip()
