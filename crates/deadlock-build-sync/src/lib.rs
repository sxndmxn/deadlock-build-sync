#![forbid(unsafe_code)]
#![deny(warnings)]

mod artifact_generation;
mod artifact_transaction;
mod build_output;
mod cli;
mod cli_arguments;
mod cli_artifacts;
mod cli_build;
mod cli_generation;
mod cli_installation;
mod cli_output;
mod cli_paths;
mod cli_quality;
mod cli_recommendation;
mod cli_refresh;
mod cli_status;
mod freshness;
mod generation;
mod generation_inputs;
mod generation_projection;
mod generation_types;
mod trace_summary;

pub use artifact_generation::write_build_artifacts;
pub use cli::run_cli;
pub use cli_arguments::Cli;
pub use generation::{GenerationRequest, generate_guides};
pub use generation_types::{GeneratedGuides, select_heroes};
