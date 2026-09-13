# Library Documentation Index

This index covers all 19 direct external libraries in the workspace manifests on September 12, 2026.
It includes `sha2` as a build dependency of `deadlock-analysis`.
The latest API links opened successfully when this index was created.
Upstream source links come from the downloaded packages' Cargo metadata.

Locked versions are a snapshot; `Cargo.lock` and the consuming crate's manifest remain authoritative.
Latest API links can resolve to a newer version without changes to this index.
Check the documentation version and enabled Cargo features before using an API.

| Library | Locked direct version | Latest API documentation | Upstream source |
|---|---|---|---|
| `base64` | 0.23.1 | [API](https://docs.rs/base64/latest/base64/) | [Source](https://github.com/marshallpierce/rust-base64) |
| `basin` | 1.11.0 | [API](https://docs.rs/basin/latest/basin/) | [Source](https://github.com/jolars/basin) |
| `chrono` | 0.4.45 | [API](https://docs.rs/chrono/latest/chrono/) | [Source](https://github.com/chronotope/chrono) |
| `clap` | 4.6.6 | [API](https://docs.rs/clap/latest/clap/) | [Source](https://github.com/clap-rs/clap) |
| `duckdb` | 1.10505.0 | [API](https://docs.rs/duckdb/latest/duckdb/) | [Source](https://github.com/duckdb/duckdb-rs) |
| `htmlize` | 1.1.0 | [API](https://docs.rs/htmlize/latest/htmlize/) | [Source](https://github.com/danielparks/htmlize) |
| `leiden-rs` | 0.8.1 | [API](https://docs.rs/leiden-rs/latest/leiden_rs/) | [Source](https://gitcode.com/lileeei/leiden-rs) |
| `lz4_flex` | 0.14.0 | [API](https://docs.rs/lz4_flex/latest/lz4_flex/) | [Source](https://github.com/pseitz/lz4_flex) |
| `ndarray` | 0.17.2 | [API](https://docs.rs/ndarray/latest/ndarray/) | [Source](https://github.com/rust-ndarray/ndarray) |
| `num-traits` | 0.2.19 | [API](https://docs.rs/num-traits/latest/num_traits/) | [Source](https://github.com/rust-num/num-traits) |
| `prost` | 0.14.4 | [API](https://docs.rs/prost/latest/prost/) | [Source](https://github.com/tokio-rs/prost) |
| `regex-lite` | 0.1.9 | [API](https://docs.rs/regex-lite/latest/regex_lite/) | [Source](https://github.com/rust-lang/regex) |
| `ruzstd` | 0.9.0 | [API](https://docs.rs/ruzstd/latest/ruzstd/) | [Source](https://github.com/KillingSpark/zstd-rs) |
| `serde` | 1.0.229 | [API](https://docs.rs/serde/latest/serde/) | [Source](https://github.com/serde-rs/serde) |
| `serde_json` | 1.0.151 | [API](https://docs.rs/serde_json/latest/serde_json/) | [Source](https://github.com/serde-rs/json) |
| `sha2` | 0.11.0 | [API](https://docs.rs/sha2/latest/sha2/) | [Source](https://github.com/RustCrypto/hashes) |
| `statrs` | 0.19.1 | [API](https://docs.rs/statrs/latest/statrs/) | [Source](https://github.com/statrs-dev/statrs) |
| `tempfile` | 3.27.0 | [API](https://docs.rs/tempfile/latest/tempfile/) | [Source](https://github.com/Stebalien/tempfile) |
| `ureq` | 3.4.1 | [API](https://docs.rs/ureq/latest/ureq/) | [Source](https://github.com/algesten/ureq) |

## Version-Specific API Pages

Replace `latest` in the API URL with the resolved Cargo version.
Keep the Rust crate identifier at the end of the URL, including underscores for names such as `num_traits`.
For example, the locked `ureq` API is at [ureq 3.4.1](https://docs.rs/ureq/3.4.1/ureq/).
Some hosted version pages can be unavailable even when the latest page opens.
Use the matching local package source when necessary.

`Cargo.lock` also contains transitive `base64` version 0.22.1.
The direct `deadlock-steam` dependency resolves to 0.23.1.
Select the version used by the consuming crate.

## Additional Upstream Guides

- [DuckDB engine documentation](https://duckdb.org/docs/current/): SQL, extensions, configuration, and execution behavior.
- [Serde guide](https://serde.rs/): serialization design, derive attributes, and custom implementations.

Rust standard library APIs follow the toolchain selected by `rust-toolchain.toml`.
Use that toolchain's local documentation when current online documentation describes a newer compiler.
