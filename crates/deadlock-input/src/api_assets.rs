use deadlock_data::Result;
use serde_json::Value;

use crate::api_session::{ApiSession, object_rows};

pub fn build_tags(session: &mut ApiSession) -> Result<Vec<Value>> {
    let parameters = session.asset_parameters()?;
    object_rows(
        session.get("/v1/assets/build-tags", parameters)?,
        "Build tag assets",
    )
}
