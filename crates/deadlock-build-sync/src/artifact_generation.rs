use std::path::Path;

use deadlock_data::{Result, atomic_write, atomic_write_json, trace_operation};
use deadlock_guides::{
    NarrativeCatalog, PolicyArtifact, PurchaseGuide, StrategyContext,
    build_strategy_context_document, generate_narrative_document, reconstruct_artifact_bundle,
};

use crate::artifact_transaction::ArtifactTransaction;
use crate::build_output::write_build_guides;
use crate::generation_types::GeneratedGuides;

pub fn strategy_context(generated: &GeneratedGuides) -> Result<StrategyContext> {
    build_strategy_context_document(
        &generated.patch,
        generated.contexts.clone(),
        &generated.manifest,
        generated.item_mechanics.clone(),
        &generated.coverage,
    )
}

pub fn policy_artifact(generated: &GeneratedGuides) -> Result<PolicyArtifact> {
    PolicyArtifact::new(
        generated.policies.clone(),
        generated.manifest.clone(),
        generated.coverage.clone(),
    )
}

/// # Errors
/// Returns an error when generation is incomplete, artifacts fail validation, or guarded directory replacement fails.
pub fn write_build_artifacts(
    directory: &Path,
    generated: &GeneratedGuides,
) -> Result<Vec<PurchaseGuide>> {
    let evidence = &generated.evidence;
    generated.require_complete()?;
    let transaction = ArtifactTransaction::new(directory)?;
    let staged = transaction.staged();
    let context = strategy_context(generated)?;
    let policies = policy_artifact(generated)?;
    let existing_path = staged.join("narratives.json");
    let existing = if existing_path.try_exists()? {
        Some(NarrativeCatalog::load(&existing_path)?)
    } else {
        None
    };
    let narratives = trace_operation(
        "artifacts.generate_narratives",
        Some("generate_narratives"),
        || {
            generate_narrative_document(
                &context,
                &[],
                existing.as_ref(),
                false,
                &chrono::Utc::now().to_rfc3339(),
            )
        },
    )?;
    let bundle = trace_operation("artifacts.validate_bundle", Some("validate_bundle"), || {
        reconstruct_artifact_bundle(&context, &policies, &narratives.catalog, evidence)
    })?;
    atomic_write(&staged.join("build-evidence.json"), evidence.raw_bytes())?;
    atomic_write_json(&staged.join("strategy-context.json"), context.document())?;
    atomic_write_json(&staged.join("policies.json"), &policies.to_document()?)?;
    atomic_write_json(
        &staged.join("narratives.json"),
        narratives.catalog.document(),
    )?;
    write_build_guides(staged, directory, &bundle.guides, generated)?;
    trace_operation("artifacts.install_bundle", Some("install_bundle"), || {
        transaction.commit()
    })?;
    Ok(bundle.guides)
}
