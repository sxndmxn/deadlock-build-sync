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
    #[arg(long, global = true, default_value = DEFAULT_API_BASE_URL)]
    pub api_base_url: String,
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
    #[arg(long, value_parser = clap::value_parser!(u32).range(1..))]
    pub account_id: Option<u32>,
    #[arg(long)]
    pub cache_path: Option<PathBuf>,
}

#[derive(Debug, Args)]
pub struct BuildArguments {
    /// Directory for hero-builds.json and the Markdown builds.
    #[arg(long)]
    pub artifacts: Option<PathBuf>,
    #[arg(long, default_value = "ritualist-i")]
    pub min_rank: Rank,
    #[arg(long, default_value = "eternus-v")]
    pub max_rank: Rank,
    /// Name of the analysis run. Use with --resume to reuse its extracted matches.
    #[arg(long)]
    pub run_id: Option<String>,
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
    #[arg(long, default_value = "8", value_parser = clap::value_parser!(u16).range(1..))]
    pub extraction_threads: u16,
}

#[derive(Debug, Args)]
pub struct SyncArguments {
    #[command(flatten)]
    pub build: BuildArguments,
    #[command(flatten)]
    pub location: LocationArguments,
    #[arg(long)]
    pub persona: Option<String>,
}

#[derive(Debug, Args)]
pub struct InstallArguments {
    #[command(flatten)]
    pub location: LocationArguments,
    #[arg(long)]
    pub artifacts: Option<PathBuf>,
    #[arg(long)]
    pub persona: Option<String>,
}

#[derive(Debug, Args)]
pub struct StatusArguments {
    #[command(flatten)]
    pub location: LocationArguments,
    #[arg(long)]
    pub artifacts: Option<PathBuf>,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct RestoreArguments {
    #[command(flatten)]
    pub location: LocationArguments,
    #[arg(long, required = true)]
    pub latest: bool,
}

#[derive(Debug, Args)]
pub struct TraceSummaryArguments {
    pub path: PathBuf,
    #[arg(long, default_value = "200", value_parser = clap::value_parser!(u32).range(1..))]
    pub max_nodes: u32,
}
