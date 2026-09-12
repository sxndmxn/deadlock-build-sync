COPY compositions TO $path (
    FORMAT parquet,
    COMPRESSION zstd,
    ROW_GROUP_SIZE 100000
);
