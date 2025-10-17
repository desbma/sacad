//! Deezer cover source

use std::sync::Arc;

use anyhow::Context as _;
use itertools::Itertools as _;
use reqwest::Url;

use crate::{
    cl::SourceName,
    cover::{Cover, Format, Metadata},
    http::SourceHttpClient,
    source::{self, Source, normalize},
};

/// Deezer cover source
pub(crate) struct Deezer;

#[derive(Debug, serde::Serialize, serde::Deserialize)]
struct Response {
    data: Vec<ResponseTrack>,
}

#[derive(Debug, serde::Serialize, serde::Deserialize)]
struct ResponseTrack {
    artist: ResponseArtist,
    album: ResponseAlbum,
}

#[derive(Debug, serde::Serialize, serde::Deserialize)]
struct ResponseArtist {
    id: u64,
    name: String,
}

#[derive(Debug, serde::Serialize, serde::Deserialize)]
struct ResponseAlbum {
    id: u64,
    title: String,
    cover_small: Option<String>,
    cover_medium: Option<String>,
    cover_big: Option<String>,
    cover_xl: Option<String>,
}

/// Cover sizes available from Deezer API
const COVER_SIZES: &[(&str, u32)] = &[
    ("cover_small", 56),
    ("cover_medium", 250),
    ("cover_big", 500),
    ("cover_xl", 1000),
];

/// Default relevance for Deezer covers
const DEEZER_RELEVANCE: source::Relevance = source::Relevance {
    fuzzy: false,
    only_front_covers: true,
    unrelated_risk: false,
};

impl ResponseAlbum {
    /// Get cover URL by size key
    fn cover_url(&self, key: &str) -> Option<&str> {
        match key {
            "cover_small" => self.cover_small.as_deref(),
            "cover_medium" => self.cover_medium.as_deref(),
            "cover_big" => self.cover_big.as_deref(),
            "cover_xl" => self.cover_xl.as_deref(),
            _ => None,
        }
    }
}

#[async_trait::async_trait]
impl Source for Deezer {
    async fn search(
        &self,
        artist: &str,
        album: &str,
        http: &mut Arc<SourceHttpClient>,
    ) -> anyhow::Result<Vec<Cover>> {
        let nartist = normalize(artist);
        let nalbum = normalize(album);
        let query = format!("artist:\"{nartist}\" album:\"{nalbum}\"");
        let url_params = [("q", query.as_str()), ("order", "RANKING")];

        // Note: source has pagination but getting the first 25 seems enough
        #[expect(clippy::unwrap_used)]
        let search_url =
            Url::parse_with_params("https://api.deezer.com/search", url_params).unwrap();
        let resp: Response = http.get_json(search_url).await?;

        let mut results = Vec::new();
        for (rank, result) in resp
            .data
            .into_iter()
            .unique_by(|t| (t.artist.id, t.album.id))
            .enumerate()
        {
            let Some(thumbnail_url_str) = result.album.cover_small.as_deref() else {
                continue;
            };
            let thumbnail_url: Url = thumbnail_url_str
                .parse()
                .with_context(|| format!("Failed to parse thumbnail URL {thumbnail_url_str:?}"))?;

            for &(key, size) in COVER_SIZES {
                let Some(url_str) = result.album.cover_url(key) else {
                    continue;
                };
                let url: Url = url_str
                    .parse()
                    .with_context(|| format!("Failed to parse cover URL {url_str:?}"))?;

                let cover = Cover {
                    url,
                    thumbnail_url: thumbnail_url.clone(),
                    size_px: Metadata::known((size, size)),
                    format: Metadata::known(Format::Jpeg),
                    source_name: SourceName::Deezer,
                    source_http: Arc::clone(http),
                    relevance: source::Relevance {
                        fuzzy: (normalize(&result.artist.name) != nartist)
                            || (normalize(&result.album.title) != nalbum),
                        ..DEEZER_RELEVANCE
                    },
                    rank,
                };
                results.push(cover);
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
        let source = Deezer;
        source_has_results(source, SourceName::Deezer).await;
    }

    #[tokio::test]
    async fn has_no_results() {
        let _ = simple_logger::init_with_env();
        let source = Deezer;
        source_no_results(source, SourceName::Deezer).await;
    }
}
