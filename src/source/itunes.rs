//! Itunes cover source

use std::sync::Arc;

use anyhow::Context as _;
use reqwest::Url;
use strum::IntoEnumIterator as _;

use crate::{
    cl::SourceName,
    cover::{self, Cover},
    http::SourceHttpClient,
    source::{self, Source, normalize, remove_chars},
};

/// Itunes cover source
pub(crate) struct Itunes;

#[derive(Debug, serde::Serialize, serde::Deserialize)]
struct Response {
    results: Vec<ResponseResult>,
}

#[derive(Debug, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct ResponseResult {
    collection_name: String,
    artist_name: String,
    artwork_url_60: String,
    artwork_url_100: String,
}

/// Default relevance for Itunes covers
const ITUNES_RELEVANCE: source::Relevance = source::Relevance {
    fuzzy: false,
    only_front_covers: true,
    unrelated_risk: false,
};

#[async_trait::async_trait]
impl Source for Itunes {
    async fn search(
        &self,
        artist: &str,
        album: &str,
        http: &mut Arc<SourceHttpClient>,
    ) -> anyhow::Result<Vec<Cover>> {
        let nartist = remove_chars(normalize(artist), |c| {
            c.is_ascii() && !c.is_ascii_control() && !c.is_ascii_punctuation()
        });
        let nalbum = remove_chars(normalize(album), |c| {
            c.is_ascii() && !c.is_ascii_control() && !c.is_ascii_punctuation()
        });
        let url_term = format!("{nartist} {nalbum}");
        let url_params = [("media", "music"), ("entity", "album"), ("term", &url_term)];
        #[expect(clippy::unwrap_used)] // base URL is absolute
        let search_url =
            Url::parse_with_params("https://itunes.apple.com/search", url_params).unwrap();
        let resp: Response = http.get_json(search_url).await?;
        let mut results = Vec::new();
        for (rank, result) in resp
            .results
            .into_iter()
            .filter(|r| {
                (normalize(&r.collection_name).starts_with(&nalbum))
                    && (normalize(&r.artist_name) == nartist)
            })
            .enumerate()
        {
            let thumbnail_url: Url = result
                .artwork_url_60
                .parse()
                .with_context(|| format!("Failed to parse URL {:?}", result.artwork_url_60))?;
            for candidate_size in [5000, 1200, 600] {
                for candidate_format in cover::Format::iter() {
                    let candidate_url = format!(
                        "{}/{}x{}{}",
                        result
                            .artwork_url_60
                            .rsplit_once('/')
                            .ok_or_else(|| anyhow::anyhow!("Unable to build cover URL"))?
                            .0,
                        candidate_size,
                        candidate_size,
                        match candidate_format {
                            cover::Format::Png => ".png",
                            cover::Format::Jpeg => "-100.jpg",
                        }
                    )
                    .parse::<Url>()
                    .context("Unable to build cover URL")?;
                    log::trace!("Probing URL {candidate_url}");
                    if http
                        .head(candidate_url.clone())
                        .await
                        .with_context(|| format!("Unable to probe URL {candidate_url:?}"))?
                    {
                        let cover = Cover {
                            url: candidate_url,
                            thumbnail_url: thumbnail_url.clone(),
                            size_px: cover::Metadata::known((candidate_size, candidate_size)),
                            format: cover::Metadata::known(candidate_format),
                            source_name: SourceName::Itunes,
                            source_http: Arc::clone(http),
                            relevance: source::Relevance {
                                fuzzy: normalize(&result.collection_name) != nalbum,
                                ..ITUNES_RELEVANCE
                            },
                            rank,
                        };
                        results.push(cover);
                    }
                }
            }
        }
        Ok(results)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::source::tests::{source_has_results, source_no_results};

    #[tokio::test]
    async fn has_results() {
        let _ = simple_logger::init_with_env();
        let source = Itunes;
        source_has_results(source, SourceName::Itunes).await;
    }

    #[tokio::test]
    async fn has_no_results() {
        let _ = simple_logger::init_with_env();
        let source = Itunes;
        source_no_results(source, SourceName::Itunes).await;
    }
}
