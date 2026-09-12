use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;
use std::process::Command;

use serde_json::Value;

use crate::error::Result;

pub fn check(root: &Path) -> Result<()> {
    let metadata = Command::new("cargo")
        .args(["metadata", "--no-deps", "--format-version", "1", "--locked"])
        .current_dir(root)
        .output()?;
    if !metadata.status.success() {
        return Err("Cargo could not read the workspace metadata".into());
    }
    let metadata: Value = serde_json::from_slice(&metadata.stdout)?;
    let packages = metadata["packages"]
        .as_array()
        .ok_or("Cargo metadata has no package list")?;
    check_crate_boundaries(packages)?;
    for package in packages {
        let name = package["name"]
            .as_str()
            .ok_or("Cargo package has no name")?;
        let targets = package["targets"]
            .as_array()
            .ok_or("Cargo package has no targets")?;
        for target in targets {
            check_target(root, name, target)?;
        }
    }
    Ok(())
}

fn check_crate_boundaries(packages: &[Value]) -> Result<()> {
    let names = packages
        .iter()
        .map(|package| package["name"].as_str().ok_or("Cargo package has no name"))
        .collect::<std::result::Result<BTreeSet<_>, _>>()?;
    for package in packages {
        let name = package["name"]
            .as_str()
            .ok_or("Cargo package has no name")?;
        let allowed = allowed_dependencies(name)?;
        for dependency in package["dependencies"]
            .as_array()
            .ok_or("Cargo package has no dependency list")?
        {
            let target = dependency["name"]
                .as_str()
                .ok_or("Cargo dependency has no name")?;
            if names.contains(target) && !allowed.contains(&target) {
                return Err(format!("Crate boundary rejects {name} -> {target}").into());
            }
        }
    }
    Ok(())
}

fn allowed_dependencies(package: &str) -> Result<&'static [&'static str]> {
    match package {
        "deadlock-data" | "deadlock-quality" => Ok(&[]),
        "deadlock-input" => Ok(&["deadlock-data"]),
        "deadlock-guides" => Ok(&["deadlock-data", "deadlock-input"]),
        "deadlock-steam" => Ok(&["deadlock-data", "deadlock-guides"]),
        "deadlock-analysis" => Ok(&["deadlock-data", "deadlock-input", "deadlock-guides"]),
        "deadlock-build-sync" => Ok(&[
            "deadlock-data",
            "deadlock-input",
            "deadlock-guides",
            "deadlock-steam",
            "deadlock-analysis",
        ]),
        _ => Err(format!("Crate has no reviewed dependency boundary: {package}").into()),
    }
}

fn check_target(root: &Path, package: &str, target: &Value) -> Result<()> {
    let kinds = target["kind"]
        .as_array()
        .ok_or("Cargo target has no kind")?;
    let mut command = Command::new("cargo");
    command.args([
        "modules",
        "dependencies",
        "--package",
        package,
        "--all-features",
        "--no-externs",
        "--no-sysroot",
        "--no-owns",
        "--no-fns",
        "--no-types",
        "--no-traits",
    ]);
    if kinds.iter().any(|kind| kind == "lib") {
        command.arg("--lib");
    } else if kinds.iter().any(|kind| kind == "bin") {
        command.args([
            "--bin",
            target["name"]
                .as_str()
                .ok_or("Cargo binary target has no name")?,
        ]);
    } else {
        return Ok(());
    }
    let output = command.current_dir(root).output()?;
    if !output.status.success() {
        return Err(format!(
            "Module analysis failed for {package}: {}",
            String::from_utf8_lossy(&output.stderr)
        )
        .into());
    }
    check_graph(std::str::from_utf8(&output.stdout)?)
}

fn check_graph(source: &str) -> Result<()> {
    let mut dependencies = BTreeMap::<String, BTreeSet<String>>::new();
    for line in source.lines() {
        let line = line.trim();
        let Some((start, end)) = line
            .strip_prefix('"')
            .and_then(|line| line.split_once("\" -> \""))
        else {
            continue;
        };
        let end = end
            .split_once('"')
            .ok_or("Module dependency output has an invalid edge")?
            .0;
        dependencies
            .entry(start.to_owned())
            .or_default()
            .insert(end.to_owned());
        dependencies.entry(end.to_owned()).or_default();
    }
    if dependencies.is_empty() && !source.contains("// \"crate\" node") {
        return Err("Module analysis returned no crate graph".into());
    }
    remove_acyclic_nodes(dependencies)
}

fn remove_acyclic_nodes(mut dependencies: BTreeMap<String, BTreeSet<String>>) -> Result<()> {
    while !dependencies.is_empty() {
        let resolved = dependencies
            .iter()
            .filter(|(_, edges)| edges.is_empty())
            .map(|(name, _)| name.clone())
            .collect::<BTreeSet<_>>();
        if resolved.is_empty() {
            let names = dependencies.keys().cloned().collect::<Vec<_>>().join(", ");
            return Err(format!("Cyclic module dependencies remain: {names}").into());
        }
        dependencies.retain(|name, _| !resolved.contains(name));
        for edges in dependencies.values_mut() {
            edges.retain(|name| !resolved.contains(name));
        }
    }
    Ok(())
}
