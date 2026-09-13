use deadlock_data::Result;

use crate::cli_arguments::RefreshArguments;

#[cfg(not(feature = "analysis"))]
pub fn run_refresh(_arguments: &RefreshArguments, _base_url: &str) -> Result<u8> {
    Err(deadlock_data::Error::new(
        "This binary requires the analysis feature for refresh-evidence. Build with cargo build --release --features analysis.",
    ))
}

#[cfg(feature = "analysis")]
pub fn run_refresh(arguments: &RefreshArguments, base_url: &str) -> Result<u8> {
    use deadlock_analysis::{
        ExtractionResources, RefreshRequest, parse_timestamp, refresh_evidence,
    };
    use deadlock_data::{Rank, RankRange, state_directory};
    use deadlock_guides::RankExpansion;

    use crate::cli_arguments::RankExpansion as ExpansionArgument;
    use crate::cli_output::print_text;
    use crate::cli_paths::artifact_directory;

    let request = RefreshRequest {
        output: artifact_directory(arguments.artifacts.as_deref())?.join("build-evidence.json"),
        root: state_directory()?.join("offline"),
        run_id: arguments.run_id.clone(),
        since: arguments
            .since
            .as_deref()
            .map(parse_timestamp)
            .transpose()?,
        as_of: arguments
            .as_of
            .as_deref()
            .map(parse_timestamp)
            .transpose()?,
        ranks: RankRange {
            minimum: arguments
                .min_badge
                .map(Rank::try_from)
                .transpose()?
                .unwrap_or(arguments.ranks.min_rank),
            maximum: arguments
                .max_badge
                .map(Rank::try_from)
                .transpose()?
                .unwrap_or(arguments.ranks.max_rank),
        },
        rank_expansion: match arguments.ranks.rank_expansion {
            ExpansionArgument::Auto => RankExpansion::Auto,
            ExpansionArgument::Off => RankExpansion::Off,
        },
        workers: arguments.workers,
        extraction_resources: ExtractionResources {
            memory_limit_mb: arguments.extraction_memory_mb,
            threads: arguments.extraction_threads,
        },
        resume: arguments.resume,
        api_base_url: base_url.into(),
    };
    let result = refresh_evidence(&request)?;
    print_text(&format!(
        "Evidence: {} ({})\nSource and admission reports: {}\n",
        result.output.display(),
        result.artifact_id,
        result.run_directory.display()
    ))?;
    Ok(0)
}
