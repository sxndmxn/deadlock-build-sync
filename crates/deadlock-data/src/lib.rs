#![forbid(unsafe_code)]
#![deny(warnings)]

mod artifact;
mod error;
mod execution_trace;
mod json;
mod rank;
mod statistics;

pub use artifact::{atomic_write, atomic_write_json, read_json, state_directory};
pub use error::{Error, Result};
pub use execution_trace::{TraceSession, trace_operation};
pub use json::{
    array, canonical_json, field, fingerprint, integer, object, sha256, text, validate_sha256,
};
pub use rank::{Rank, RankRange};
pub use statistics::{ObservationCounts, count_as_f64};
