//! Temporary: prints the stored size of each category in each private build.
use std::path::Path;

use prost::Message;

#[derive(Clone, PartialEq, prost::Message)]
struct Envelope {
    #[prost(bytes = "vec", optional, tag = "1")]
    build: Option<Vec<u8>>,
}

#[derive(Clone, PartialEq, prost::Message)]
struct Item {
    #[prost(uint64, optional, tag = "1")]
    item_id: Option<u64>,
}

#[derive(Clone, PartialEq, prost::Message)]
struct Category {
    #[prost(message, repeated, tag = "1")]
    items: Vec<Item>,
    #[prost(string, optional, tag = "2")]
    name: Option<String>,
    #[prost(float, optional, tag = "4")]
    width: Option<f32>,
    #[prost(float, optional, tag = "5")]
    height: Option<f32>,
}

#[derive(Clone, PartialEq, prost::Message)]
struct Details {
    #[prost(message, repeated, tag = "1")]
    categories: Vec<Category>,
}

#[derive(Clone, PartialEq, prost::Message)]
struct Build {
    #[prost(uint64, optional, tag = "2")]
    hero_id: Option<u64>,
    #[prost(string, optional, tag = "5")]
    name: Option<String>,
    #[prost(string, optional, tag = "6")]
    description: Option<String>,
    #[prost(uint64, optional, tag = "7")]
    update_timestamp: Option<u64>,
    #[prost(message, optional, tag = "10")]
    details: Option<Details>,
}

fn decode(bytes: &[u8]) -> Option<Build> {
    let inner = Envelope::decode(bytes)
        .ok()
        .and_then(|envelope| envelope.build);
    let candidate = inner.as_deref().unwrap_or(bytes);
    Build::decode(candidate)
        .ok()
        .filter(|build| build.hero_id.is_some() && build.name.is_some())
        .or_else(|| Build::decode(bytes).ok())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = std::env::args()
        .nth(1)
        .ok_or("usage: dump_category_sizes CACHE")?;
    let cache = deadlock_steam::read_cache(Path::new(&path))?;
    for value in cache.document().root.field("Unpublished")?.array()? {
        let Ok(bytes) = value.blob() else { continue };
        let Some(build) = decode(bytes) else { continue };
        let managed = build
            .description
            .as_deref()
            .is_some_and(|text| text.contains("Build path: "));
        println!(
            "hero={} managed={} updated={} name={:?}",
            build.hero_id.unwrap_or(0),
            managed,
            build.update_timestamp.unwrap_or(0),
            build.name.unwrap_or_default()
        );
        for category in build
            .details
            .map(|details| details.categories)
            .unwrap_or_default()
        {
            println!(
                "  items={:>2} width={:>9.4} height={:>9.4} {:?}",
                category.items.len(),
                category.width.unwrap_or(-1.0),
                category.height.unwrap_or(-1.0),
                category.name.unwrap_or_default()
            );
        }
    }
    Ok(())
}
