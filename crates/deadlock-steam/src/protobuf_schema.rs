#[derive(Clone, Eq, PartialEq, prost::Message)]
pub struct ItemModification {
    #[prost(uint64, required, tag = "1")]
    pub item_id: u64,
    #[prost(string, required, tag = "2")]
    pub annotation: String,
    #[prost(uint32, optional, tag = "3")]
    pub required_flex_slots: Option<u32>,
    #[prost(uint32, optional, tag = "4")]
    pub sell_priority: Option<u32>,
    #[prost(uint64, optional, tag = "5")]
    pub imbue_target_ability_id: Option<u64>,
}

#[derive(Clone, PartialEq, prost::Message)]
pub struct Category {
    #[prost(message, repeated, tag = "1")]
    pub items: Vec<ItemModification>,
    #[prost(string, required, tag = "2")]
    pub name: String,
    #[prost(string, required, tag = "3")]
    pub description: String,
    #[prost(float, required, tag = "4")]
    pub width: f32,
    #[prost(float, required, tag = "5")]
    pub height: f32,
    #[prost(bool, required, tag = "6")]
    pub optional: bool,
}

#[derive(Clone, Eq, PartialEq, prost::Message)]
pub struct AbilityPurchase {
    #[prost(uint64, required, tag = "1")]
    pub ability_id: u64,
    #[prost(uint32, required, tag = "2")]
    pub currency_type: u32,
    #[prost(int64, required, tag = "3")]
    pub delta: i64,
    #[prost(string, optional, tag = "4")]
    pub annotation: Option<String>,
}

#[derive(Clone, Eq, PartialEq, prost::Message)]
pub struct AbilityOrder {
    #[prost(message, repeated, tag = "1")]
    pub purchases: Vec<AbilityPurchase>,
}

#[derive(Clone, PartialEq, prost::Message)]
pub struct Details {
    #[prost(message, repeated, tag = "1")]
    pub categories: Vec<Category>,
    #[prost(message, optional, tag = "2")]
    pub abilities: Option<AbilityOrder>,
}

#[derive(Clone, PartialEq, prost::Message)]
pub struct HeroBuild {
    #[prost(uint64, required, tag = "1")]
    pub build_id: u64,
    #[prost(uint64, required, tag = "2")]
    pub hero_id: u64,
    #[prost(uint64, required, tag = "3")]
    pub author_account_id: u64,
    #[prost(uint64, required, tag = "4")]
    pub timestamp: u64,
    #[prost(string, required, tag = "5")]
    pub name: String,
    #[prost(string, required, tag = "6")]
    pub description: String,
    #[prost(uint64, required, tag = "7")]
    pub update_timestamp: u64,
    #[prost(uint64, required, tag = "8")]
    pub version: u64,
    #[prost(uint64, required, tag = "9")]
    pub source_build_id: u64,
    #[prost(message, required, tag = "10")]
    pub details: Details,
    #[prost(uint64, repeated, packed = "false", tag = "11")]
    pub tag_ids: Vec<u64>,
    #[prost(bool, required, tag = "12")]
    pub published: bool,
}

#[derive(Clone, Eq, PartialEq, prost::Message)]
pub struct Envelope {
    #[prost(bytes = "vec", required, tag = "1")]
    pub build: Vec<u8>,
    #[prost(bytes = "vec", required, tag = "2")]
    pub user_data: Vec<u8>,
    #[prost(uint64, required, tag = "3")]
    pub status: u64,
    #[prost(uint64, required, tag = "8")]
    pub timestamp: u64,
}
