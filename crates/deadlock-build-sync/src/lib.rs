#![forbid(unsafe_code)]
#![deny(warnings)]

mod artifact_transaction;
mod build_markdown;
mod build_workflow;
mod cli;
mod cli_arguments;
mod cli_commands;
mod cli_output;
mod cli_paths;
mod freshness;
mod trace_summary;

pub use build_workflow::{CATALOG_FILE, install_catalog, write_build_artifacts};
pub use cli::run_cli;
pub use cli_arguments::Cli;
