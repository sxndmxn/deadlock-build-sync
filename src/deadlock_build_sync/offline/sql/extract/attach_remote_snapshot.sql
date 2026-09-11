-- SQLFluff 4.3 does not parse DuckDB ATTACH.
ATTACH 'ducklake:deadlock_ducklake' AS remote ( -- noqa: PRS
    READ_ONLY,
    SNAPSHOT_VERSION $version
);
