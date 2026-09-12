use std::collections::BTreeMap;

use deadlock_data::{Result, integer};
use deadlock_guides::{MECHANIC_TAGS, extract_description_text};
use serde_json::{Value, json};

pub fn describe_overlap(hero: &Value, items: &[u64], assets: &[Value]) -> Result<Value> {
    let classes = assets
        .iter()
        .filter_map(|asset| asset["class_name"].as_str().map(|name| (name, asset)))
        .collect::<BTreeMap<_, _>>();
    let by_id = assets
        .iter()
        .map(|asset| Ok((integer(asset, "id")?, asset)))
        .collect::<Result<BTreeMap<_, _>>>()?;
    let kit = hero["items"]
        .as_object()
        .into_iter()
        .flat_map(|items| items.iter())
        .filter(|(key, _)| key.starts_with("signature"))
        .filter_map(|(_, value)| value.as_str())
        .filter_map(|name| classes.get(name))
        .map(|asset| mechanic_channels(asset))
        .collect::<Result<Vec<_>>>()?;
    let item_channels = items
        .iter()
        .map(|item| {
            let asset = by_id
                .get(item)
                .ok_or_else(|| deadlock_data::Error::new("Core item has no mechanics asset"))?;
            Ok((item.to_string(), mechanic_channels(asset)?))
        })
        .collect::<Result<BTreeMap<_, _>>>()?;
    let mut focuses = Vec::new();
    for (channel, _, _) in MECHANIC_TAGS {
        let supporting = item_channels
            .values()
            .filter_map(|value| value.get(channel))
            .collect::<Vec<_>>();
        let abilities = kit
            .iter()
            .filter_map(|value| value.get(channel))
            .collect::<Vec<_>>();
        if supporting.len() >= 2 && !abilities.is_empty() {
            focuses.push(json!({"channel":channel,"items":supporting,"abilities":abilities}));
        }
    }
    Ok(
        json!({"supported_focus":!focuses.is_empty(),"reason":if focuses.is_empty(){Some("No documented ability mechanic is shared by two core items")}else{None},
        "focuses":focuses,"item_evidence":item_channels,"limitation":"Shared mechanic text supports review. It does not verify an interaction or measure synergy."}),
    )
}

fn mechanic_channels(asset: &Value) -> Result<BTreeMap<String, Value>> {
    let description = extract_description_text(&asset["description"]);
    let lower = description.to_lowercase();
    let identifier = integer(asset, "id")?;
    Ok(MECHANIC_TAGS.into_iter().filter_map(|(channel,_,phrases)| {
        let matches = phrases.iter().filter(|phrase|lower.contains(**phrase)).collect::<Vec<_>>();
        (!matches.is_empty()).then(||(channel.into(),json!({"asset_id":identifier,"name":asset["name"],"ref":format!("asset:item:{identifier}:description"),"matched_phrases":matches,"description":description})))
    }).collect())
}
