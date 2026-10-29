use std::path::PathBuf;

use clap::{Args, Parser, Subcommand, ValueEnum};
use deadlock_data::Rank;
use deadlock_input::DEFAULT_API_BASE_URL;

#[derive(Clone, Copy, Debug, Eq, PartialEq, ValueEnum)]
pub enum TraceMode {
    Stages,
    Calls,
}

#[derive(Debug, Parser)]
#[command(
    name = "deadlock-build-sync",
    version,
    about = "Generate and install private Deadlock hero builds."
)]
pub struct Cli {
    /// Base URL of the Deadlock API.
    #[arg(long, global = true, default_value = DEFAULT_API_BASE_URL)]
    pub api_base_url: String,
    /// Write an execution trace: workflow stages or instrumented calls.
    #[arg(long, global = true, value_enum, env = "DEADLOCK_BUILD_SYNC_TRACE")]
    pub trace: Option<TraceMode>,
    #[command(subcommand)]
    pub command: Command,
}

#[derive(Debug, Subcommand)]
pub enum Command {
    /// Generate a build for every hero and install the builds in Steam.
    Sync(SyncArguments),
    /// Generate a build for every hero without Steam changes.
    Build(BuildArguments),
    /// Install the generated builds without new analysis.
    Install(InstallArguments),
    /// Check the generated and installed builds without changes.
    Status(StatusArguments),
    /// Restore the latest complete cache backup.
    Restore(RestoreArguments),
    /// Display an execution trace summary.
    TraceSummary(TraceSummaryArguments),
}

impl Command {
    #[must_use]
    pub const fn name(&self) -> &'static str {
        match self {
            Self::Sync(_) => "sync",
            Self::Build(_) => "build",
            Self::Install(_) => "install",
            Self::Status(_) => "status",
            Self::Restore(_) => "restore",
            Self::TraceSummary(_) => "trace-summary",
        }
    }
}

#[derive(Debug, Args)]
pub struct LocationArguments {
    /// Steam account ID of the cache. Required when more than one account has a cache.
    #[arg(long, value_parser = clap::value_parser!(u32).range(1..))]
    pub account_id: Option<u32>,
    /// Path of the Steam hero build cache file. The default is a search of the Steam directories.
    #[arg(long)]
    pub cache_path: Option<PathBuf>,
}

#[derive(Debug, Args)]
pub struct BuildArguments {
    /// Directory for hero-builds.json and the Markdown builds.
    #[arg(long)]
    pub artifacts: Option<PathBuf>,
    /// Lowest average match rank, for example ritualist-i.
    #[arg(long, default_value = "ritualist-i")]
    pub min_rank: Rank,
    /// Highest average match rank, for example eternus-v.
    #[arg(long, default_value = "eternus-v")]
    pub max_rank: Rank,
    /// Name of the analysis run. Use with --resume to reuse its extracted matches.
    #[arg(long)]
    pub run_id: Option<String>,
    /// Reuse the extracted matches of --run-id.
    #[arg(long, requires = "run_id")]
    pub resume: bool,
    /// First match start time (ISO 8601). The default is the current patch.
    #[arg(long)]
    pub since: Option<String>,
    /// Last match end time (ISO 8601). The default is now.
    #[arg(long)]
    pub as_of: Option<String>,
    /// Extraction memory limit in decimal megabytes.
    #[arg(long, default_value = "12000", value_parser = clap::value_parser!(u32).range(1..))]
    pub extraction_memory_mb: u32,
    /// Database threads. The match download uses at least 64.
    #[arg(long, default_value = "8", value_parser = clap::value_parser!(u16).range(1..))]
    pub extraction_threads: u16,
}

#[derive(Debug, Args)]
pub struct SyncArguments {
    #[command(flatten)]
    pub build: BuildArguments,
    #[command(flatten)]
    pub location: LocationArguments,
    /// Name at the start of each build title. The default is the local Steam name.
    #[arg(long)]
    pub persona: Option<String>,
}

#[derive(Debug, Args)]
pub struct InstallArguments {
    #[command(flatten)]
    pub location: LocationArguments,
    /// Directory for hero-builds.json and the Markdown builds.
    #[arg(long)]
    pub artifacts: Option<PathBuf>,
    /// Name at the start of each build title. The default is the local Steam name.
    #[arg(long)]
    pub persona: Option<String>,
}

#[derive(Debug, Args)]
pub struct StatusArguments {
    #[command(flatten)]
    pub location: LocationArguments,
    /// Directory for hero-builds.json and the Markdown builds.
    #[arg(long)]
    pub artifacts: Option<PathBuf>,
    /// Print the report as JSON.
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct RestoreArguments {
    #[command(flatten)]
    pub location: LocationArguments,
    /// Restore the latest complete backup. The current cache gets a backup first.
    #[arg(long, required = true)]
    pub latest: bool,
}

#[derive(Debug, Args)]
pub struct TraceSummaryArguments {
    /// Trace directory or trace.jsonl file.
    pub path: PathBuf,
    /// Largest number of call tree lines to show.
    #[arg(long, default_value = "200", value_parser = clap::value_parser!(u32).range(1..))]
    pub max_nodes: u32,
}
