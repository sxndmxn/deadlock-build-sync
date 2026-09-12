-- SQLFluff 4.3 does not parse DuckDB INSTALL and LOAD.
INSTALL icu; -- noqa: PRS
LOAD icu;
SET timezone = 'UTC';
INSTALL ducklake;
LOAD ducklake;
INSTALL httpfs;
LOAD httpfs;
