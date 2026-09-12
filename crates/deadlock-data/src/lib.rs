#![forbid(unsafe_code)]
#![deny(warnings)]

mod artifact;
mod artifact_coverage;
mod error;
mod evidence;
mod execution_trace;
mod file_fingerprint;
mod fingerprint_layers;
mod json;
mod rank;
mod rank_catalog;
mod snapshot;
mod statistics;
mod workers;

pub use artifact::{
    atomic_write, atomic_write_json, read_fingerprinted_json, read_json, read_json_bytes,
    state_directory,
};
pub use artifact_coverage::{ArtifactCoverage, BuildKey, parse_build_key};
pub use error::{Error, Result};
pub use evidence::{
    EpochBoundary, EpochSet, EvidenceRecord, EvidenceRecorder, EvidenceSemantics, EvidenceUnit,
    MatchMode, validate_sha256,
};
pub use execution_trace::{TraceSession, trace_operation};
pub use file_fingerprint::file_sha256;
pub use fingerprint_layers::{ArtifactCompatibility, FingerprintLayers};
pub use json::{array, canonical_json, field, fingerprint, integer, object, real, sha256, text};
pub use rank::{Rank, RankRange};
pub use rank_catalog::RankCatalog;
pub use snapshot::{SnapshotContent, SnapshotManifest, default_outcome_policy};
pub use statistics::{
    ObservationCounts, count_as_f64, count_from_probability, count_ratio, normal_quantile,
    round_decimal,
};
pub use workers::{map_jobs, map_jobs_by_cost};
