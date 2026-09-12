use deadlock_data::Result;

use crate::cli_arguments::RefreshArguments;

#[cfg(not(feature = "analysis"))]
pub fn run_refresh(_args: &RefreshArguments, _base_url: &str) -> Result<u8> {
    Err(deadlock_data::Error::new(
        "This binary requires the analysis feature for refresh-evidence. Build with cargo build --release --features analysis.",
    ))
}

#[cfg(feature = "analysis")]
pub fn run_refresh(args: &RefreshArguments, base_url: &str) -> Result<u8> {
    use deadlock_analysis::{RefreshRequest, parse_timestamp, refresh_evidence};
    use deadlock_data::{Rank, RankRange, state_directory};
    use deadlock_guides::{BuildGenerator, RankExpansion};

    use crate::cli_arguments::{Generator, RankExpansion as ExpansionArgument};
    use crate::cli_output::print_text;
    use crate::cli_paths::artifact_directory;

    let request = RefreshRequest {
        output: artifact_directory(args.artifacts.as_deref())?.join("build-evidence.json"),
        root: state_directory()?.join("offline"),
        run_id: args.run_id.clone(),
        since: args.since.as_deref().map(parse_timestamp).transpose()?,
        as_of: args.as_of.as_deref().map(parse_timestamp).transpose()?,
        ranks: RankRange {
            minimum: args
                .min_badge
                .map(Rank::try_from)
                .transpose()?
                .unwrap_or(args.ranks.min_rank),
            maximum: args
                .max_badge
                .map(Rank::try_from)
                .transpose()?
                .unwrap_or(args.ranks.max_rank),
        },
        rank_expansion: match args.ranks.rank_expansion {
            ExpansionArgument::Auto => RankExpansion::Auto,
            ExpansionArgument::Off => RankExpansion::Off,
        },
        workers: args.workers,
        resume: args.resume,
        generator: match args.generator {
            Generator::Current => BuildGenerator::Current,
            Generator::Beam => BuildGenerator::Beam,
        },
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
