use std::io::{self, Write};

use deadlock_data::Result;
use deadlock_guides::{PurchaseGuide, render_presentation_markdown, render_purchase_markdown};
use serde_json::{Value, json};

use crate::build_output::{describe_guide, presentation};
use crate::cli_arguments::OutputFormat;
use crate::generation_types::GeneratedGuides;

pub fn print_json(value: &Value) -> Result<()> {
    let mut output = io::stdout().lock();
    serde_json::to_writer_pretty(&mut output, value)?;
    writeln!(output)?;
    Ok(())
}

pub fn print_text(value: &str) -> Result<()> {
    let mut output = io::stdout().lock();
    writeln!(output, "{value}")?;
    Ok(())
}

pub fn print_guides(
    guides: &[PurchaseGuide],
    generated: &GeneratedGuides,
    format: OutputFormat,
    details: bool,
    account_id: u32,
) -> Result<()> {
    if format == OutputFormat::Markdown {
        for guide in guides {
            print_text(&if details {
                render_purchase_markdown(guide, true)?
            } else {
                render_presentation_markdown(&presentation(guide, generated)?)?
            })?;
        }
    } else {
        print_json(
            &json!({"account_id":account_id,"persona":generated.persona,"snapshot_manifest":generated.manifest.to_document()?,
            "patch":generated.patch.to_document()?,"rank_range":generated.manifest.content().rank_range,
            "exclusions":generated.coverage.exclusions(),"policies":generated.policies.iter().map(|policy| policy.to_document(true)).collect::<Result<Vec<_>>>()?,
            "guides":guides.iter().map(|guide| describe_guide(guide, generated)).collect::<Result<Vec<_>>>()?}),
        )?;
    }
    Ok(())
}
