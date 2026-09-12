#![forbid(unsafe_code)]
#![deny(warnings)]

mod arch_lint;
mod architecture;
mod error;
mod sources;

use error::Result;

fn main() -> Result<()> {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()?;
    let source_files = sources::check(&root)?;
    arch_lint::check(&root, source_files)?;
    architecture::check(&root)?;
    println!("Rust source checks, Arch-lint rules, and module dependency checks passed");
    Ok(())
}
