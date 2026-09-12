-- SQLFluff 4.3 does not parse DuckDB CREATE SECRET.
CREATE OR REPLACE SECRET deadlock_ducklake ( -- noqa: PRS
    TYPE ducklake,
    METADATA_PATH $metadata_path
);
