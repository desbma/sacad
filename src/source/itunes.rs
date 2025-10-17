//! Itunes cover source

use reqwest::Url;

use crate::{cl::SearchArgs, cover::Cover, http::Http, source::Source};

/// Itunes cover source
pub(crate) struct Itunes;

#[derive(Debug, serde::Serialize, serde::Deserialize, bitcode::Encode, bitcode::Decode)]
#[expect(clippy::missing_docs_in_private_items)]
struct Response {
    results: Vec<ResponseResult>,
}

#[derive(Debug, serde::Serialize, serde::Deserialize, bitcode::Encode, bitcode::Decode)]
#[serde(rename_all = "camelCase")]
#[expect(clippy::missing_docs_in_private_items)]
struct ResponseResult {
    collection_name: String,
    artist_name: String,
    artwork_url_60: String,
    artwork_url_100: String,
}

#[async_trait::async_trait]
impl Source for Itunes {
    async fn search(&self, query: &SearchArgs, http: &mut Http) -> anyhow::Result<Cover> {
        let url_term = format!("{} {}", query.artist, query.album);
        let url_params = [("media", "music"), ("entity", "album"), ("term", &url_term)];
        #[expect(clippy::unwrap_used)] // base URL is absolute
        let url = Url::parse_with_params("https://itunes.apple.com/search", url_params).unwrap();
        let resp: Response = http.get_json(url).await?;
        for (rank, result) in resp.results.into_iter().enumerate() {
            todo!();
        }
        todo!();
    }
}
