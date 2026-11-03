-- SQLFluff 4.3 does not parse DuckDB INSTALL and LOAD.
INSTALL icu; -- noqa: PRS
LOAD icu;
-- GLOBAL also gives UTC to the connections of the concurrent remote copies.
SET GLOBAL timezone = 'UTC';
INSTALL ducklake;
LOAD ducklake;
INSTALL httpfs;
LOAD httpfs;
