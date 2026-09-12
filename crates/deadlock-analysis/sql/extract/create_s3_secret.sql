-- SQLFluff 4.3 does not parse DuckDB CREATE SECRET.
CREATE OR REPLACE SECRET deadlock_s3 ( -- noqa: PRS
    TYPE S3,
    KEY_ID '',
    SECRET '',
    ENDPOINT 's3-cache.deadlock-api.com',
    URL_STYLE 'path',
    USE_SSL TRUE
);
