#![forbid(unsafe_code)]
#![deny(warnings)]

mod binary;
mod build_metadata;
mod cache_backup;
mod cache_discovery;
mod cache_files;
mod cache_location;
mod cache_plan;
mod cache_read;
mod cache_request;
mod cache_restore;
mod cache_scope;
mod cache_status;
mod cache_transaction;
mod kv3_compression;
mod kv3_decode;
mod kv3_encode;
mod kv3_header;
mod kv3_legacy;
mod kv3_read;
mod kv3_streams;
mod kv3_value;
mod process_check;
mod protobuf_encode;
mod protobuf_fields;
mod protobuf_schema;
mod steam_identity;

pub use build_metadata::{HeroBuildMetadata, parse_hero_build_metadata};
pub use cache_discovery::{discover_cache, steam_roots};
pub use cache_location::{CacheLocation, CacheSearch};
pub use cache_plan::{CacheUpdate, prepare_cache_update};
pub use cache_read::{SteamCache, read_cache};
pub use cache_request::{BuildKey, CacheUpdateRequest, ManagedBuild};
pub use cache_restore::{RestoreResult, restore_latest};
pub use cache_status::managed_build_descriptions;
pub use cache_transaction::{InstallResult, install_cache_update};
pub use kv3_encode::encode_kv3;
pub use kv3_read::decode_kv3;
pub use kv3_value::{Kv3Document, Kv3Flag, Kv3Kind, Kv3Value};
pub use process_check::{LinuxProcesses, ProcessInspection, require_deadlock_stopped};
pub use protobuf_encode::{encode_hero_build, wrap_hero_build};
pub use steam_identity::local_steam_persona;
