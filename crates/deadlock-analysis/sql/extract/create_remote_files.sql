CREATE OR REPLACE TEMP TABLE remote_files AS
SELECT
    data_file,
    data_file_size_bytes
FROM ducklake_list_files('remote', 'match_player', snapshot_version => $version);
