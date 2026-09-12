use std::path::PathBuf;

use clap::{Args, Parser, Subcommand, ValueEnum};
use deadlock_data::{EpochBoundary, Error, MatchMode, Rank, Result};
use deadlock_input::DEFAULT_API_BASE_URL;

#[derive(Clone, Copy, Debug, Eq, PartialEq, ValueEnum)]
pub enum OutputFormat {
    Json,
    Markdown,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, ValueEnum)]
pub enum Generator {
    Current,
    Beam,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, ValueEnum)]
pub enum RankExpansion {
    Auto,
    Off,
}

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
    /// Generate deterministic builds and install every eligible hero.
    Sync(Box<SyncArguments>),
    /// Create complete Markdown and JSON builds without Steam.
    Build(Box<BuildArguments>),
    /// Check artifacts and installed builds without changes.
    Status(StatusArguments),
    /// Rebuild current evidence without Steam.
    RefreshEvidence(Box<RefreshArguments>),
    /// Return a purchase recommendation for a state file.
    Recommend(RecommendArguments),
    /// Audit build quality and optional later replay without network access.
    QualityReport(QualityArguments),
    /// Generate and display guides without Steam changes.
    Preview(Box<PreviewArguments>),
    /// Install private guides under My Builds.
    Install(Box<InstallArguments>),
    /// Install reviewed artifacts without new analytics requests.
    InstallArtifacts(InstallArtifactArguments),
    /// Export evidence context and typed policies.
    ExportContext(Box<ExportArguments>),
    /// Generate descriptions from validated evidence context.
    GenerateNarratives(NarrativeArguments),
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
            Self::Status(_) => "status",
            Self::RefreshEvidence(_) => "refresh-evidence",
            Self::Recommend(_) => "recommend",
            Self::QualityReport(_) => "quality-report",
            Self::Preview(_) => "preview",
            Self::Install(_) => "install",
            Self::InstallArtifacts(_) => "install-artifacts",
            Self::ExportContext(_) => "export-context",
            Self::GenerateNarratives(_) => "generate-narratives",
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
pub struct SelectionArguments {
    #[arg(long, conflicts_with = "all")]
    pub hero: Option<String>,
    #[arg(long)]
    pub all: bool,
}

#[derive(Debug, Args)]
pub struct RankArguments {
    #[arg(long, value_enum, default_value = "auto")]
    pub rank_expansion: RankExpansion,
    #[arg(long, default_value = "emissary-i")]
    pub min_rank: Rank,
    #[arg(long, default_value = "eternus-v")]
    pub max_rank: Rank,
}

#[derive(Debug, Args)]
pub struct SnapshotArguments {
    #[arg(long)]
    pub build_evidence: Option<PathBuf>,
    #[arg(long, default_value = "ranked")]
    pub match_mode: MatchMode,
    #[arg(long, value_parser = clap::value_parser!(u64).range(1..))]
    pub client_version: Option<u64>,
    #[arg(long, value_parser = clap::value_parser!(i64).range(1..))]
    pub as_of_timestamp: Option<i64>,
    #[arg(long, value_parser = parse_epoch)]
    pub mechanics_epoch: Option<EpochBoundary>,
    #[arg(long, value_parser = parse_epoch)]
    pub matchmaking_epoch: Option<EpochBoundary>,
    #[arg(long, value_parser = parse_epoch)]
    pub map_objectives_epoch: Option<EpochBoundary>,
    #[arg(long, value_parser = parse_epoch)]
    pub telemetry_epoch: Option<EpochBoundary>,
}

#[derive(Debug, Args)]
pub struct GenerationArguments {
    #[command(flatten)]
    pub selection: SelectionArguments,
    #[command(flatten)]
    pub ranks: RankArguments,
    #[command(flatten)]
    pub snapshot: SnapshotArguments,
}

#[derive(Debug, Args)]
pub struct BuildArguments {
    #[command(flatten)]
    pub generation: GenerationArguments,
    #[arg(long)]
    pub artifacts: Option<PathBuf>,
    #[arg(long, value_enum, default_value = "current")]
    pub generator: Generator,
    #[arg(long, value_enum, default_value = "markdown")]
    pub format: OutputFormat,
    #[arg(long)]
    pub details: bool,
}

#[derive(Debug, Args)]
pub struct SyncArguments {
    #[command(flatten)]
    pub generation: GenerationArguments,
    #[command(flatten)]
    pub location: LocationArguments,
    #[arg(long)]
    pub artifacts: Option<PathBuf>,
    #[arg(long, value_enum, default_value = "current")]
    pub generator: Generator,
}

#[derive(Debug, Args)]
pub struct NarrativeSelection {
    #[arg(long, conflicts_with = "without_narratives")]
    pub narratives: Option<PathBuf>,
    #[arg(long)]
    pub without_narratives: bool,
}

#[derive(Debug, Args)]
pub struct InstallArguments {
    #[command(flatten)]
    pub generation: GenerationArguments,
    #[command(flatten)]
    pub location: LocationArguments,
    #[command(flatten)]
    pub narrative: NarrativeSelection,
}

#[derive(Debug, Args)]
pub struct PreviewArguments {
    #[command(flatten)]
    pub install: InstallArguments,
    #[arg(long, value_enum, default_value = "json")]
    pub format: OutputFormat,
    #[arg(long)]
    pub details: bool,
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
pub struct InstallArtifactArguments {
    #[command(flatten)]
    pub location: LocationArguments,
    #[arg(long)]
    pub artifacts: Option<PathBuf>,
    #[arg(long)]
    pub persona: Option<String>,
}

#[derive(Debug, Args)]
pub struct ExportArguments {
    #[command(flatten)]
    pub generation: GenerationArguments,
    #[command(flatten)]
    pub location: LocationArguments,
    #[arg(long)]
    pub output: PathBuf,
    #[arg(long)]
    pub policy_output: Option<PathBuf>,
}

#[derive(Debug, Args)]
pub struct NarrativeArguments {
    #[arg(long)]
    pub context: PathBuf,
    #[arg(long)]
    pub output: PathBuf,
    #[arg(long)]
    pub hero: Vec<String>,
    #[arg(long)]
    pub force: bool,
}

#[derive(Debug, Args)]
pub struct RecommendArguments {
    #[arg(long)]
    pub state: PathBuf,
    #[arg(long)]
    pub build_evidence: Option<PathBuf>,
    #[arg(long)]
    pub policies: Option<PathBuf>,
    #[arg(long)]
    pub artifacts: Option<PathBuf>,
    #[arg(long, value_enum, default_value = "json")]
    pub format: OutputFormat,
}

#[derive(Debug, Args)]
pub struct QualityArguments {
    #[arg(long)]
    pub artifacts: Option<PathBuf>,
    #[arg(long, requires = "assets")]
    pub replay: Option<PathBuf>,
    #[arg(long)]
    pub assets: Option<PathBuf>,
}

#[derive(Debug, Args)]
pub struct RefreshArguments {
    #[arg(long)]
    pub artifacts: Option<PathBuf>,
    #[arg(long)]
    pub run_id: Option<String>,
    #[arg(long)]
    pub resume: bool,
    #[arg(long, default_value = "8", value_parser = clap::value_parser!(u16).range(1..))]
    pub workers: u16,
    #[command(flatten)]
    pub ranks: RankArguments,
    #[arg(long, value_parser = clap::value_parser!(u16).range(1..))]
    pub min_badge: Option<u16>,
    #[arg(long, value_parser = clap::value_parser!(u16).range(1..))]
    pub max_badge: Option<u16>,
    #[arg(long)]
    pub since: Option<String>,
    #[arg(long)]
    pub as_of: Option<String>,
    #[arg(long, value_enum, default_value = "current")]
    pub generator: Generator,
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

fn parse_epoch(value: &str) -> Result<EpochBoundary> {
    let (identity, timestamp) = value
        .rsplit_once('@')
        .ok_or_else(|| Error::new("Epoch must use IDENTITY@UNIX_TIMESTAMP"))?;
    let boundary = EpochBoundary {
        identity: identity.trim().into(),
        start_timestamp: timestamp
            .parse()
            .map_err(|error| Error::new(format!("Invalid epoch timestamp: {error}")))?,
    };
    boundary.validate()?;
    Ok(boundary)
}
