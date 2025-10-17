//! Discogs cover source using the official API

// See https://www.discogs.com/developers

use std::sync::Arc;

use anyhow::Context as _;
use const_format::formatcp;
use reqwest::{
    Url,
    header::{HeaderMap, HeaderName, HeaderValue},
};

use crate::{
    cl::SourceName,
    cover::{Cover, Format, Metadata},
    http::SourceHttpClient,
    source::{self, Source, normalize},
};

/// Discogs cover source
pub(crate) struct Discogs;

/// Discogs API key
const API_KEY: &str = "cGWMOYjQNdWYKXDaxVnR";

/// Discogs API secret
const API_SECRET: &str = "NCyWcKHWLAvAreyjDdvVogBzVnzPEEDf";

/// Default relevance for Discogs covers
const DISCOGS_RELEVANCE: source::Relevance = source::Relevance {
    fuzzy: false,
    only_front_covers: false,
    unrelated_risk: false,
};

#[derive(Debug, serde::Deserialize)]
struct Response {
    results: Vec<ResponseResult>,
}

#[derive(Debug, serde::Deserialize)]
struct ResponseResult {
    thumb: String,
    cover_image: String,
    formats: Vec<ResponseResultFormat>,
}

#[derive(Debug, serde::Deserialize)]
struct ResponseResultFormat {
    name: String,
}

/// Try to extract image dimensions from a Discogs image URL.
/// URLs contain path segments like `w:500` and `h:500`.
fn parse_image_dimensions(url: &str) -> Option<(u32, u32)> {
    let mut width = None;
    let mut height = None;

    for segment in url.split('/').rev() {
        if let Some(w) = segment.strip_prefix("w:") {
            width = w.parse().ok();
        } else if let Some(h) = segment.strip_prefix("h:") {
            height = h.parse().ok();
        }
        if width.is_some() && height.is_some() {
            break;
        }
    }

    match (width, height) {
        (Some(w), Some(h)) => Some((w, h)),
        _ => None,
    }
}

#[async_trait::async_trait]
impl Source for Discogs {
    async fn search(
        &self,
        artist: &str,
        album: &str,
        http: &mut Arc<SourceHttpClient>,
    ) -> anyhow::Result<Vec<Cover>> {
        let nartist = normalize(artist);
        let nalbum = normalize(album);

        // Note: source has pagination but getting the first 50 results is more than enough
        let url_params = [
            ("artist", nartist.as_str()),
            ("release_title", nalbum.as_str()),
            ("type", "release"),
        ];
        #[expect(clippy::unwrap_used)]
        let search_url =
            Url::parse_with_params("https://api.discogs.com/database/search", url_params).unwrap();

        let resp: Response = http.get_json(search_url).await?;

        let mut results = Vec::new();
        for (rank, result) in resp.results.into_iter().enumerate() {
            if !result.formats.iter().any(|f| f.name == "CD") || result.thumb.trim().is_empty() {
                continue;
            }

            debug_assert!(!result.cover_image.trim().is_empty());

            let Some((width, height)) = parse_image_dimensions(&result.cover_image) else {
                continue;
            };

            let url: Url = result
                .cover_image
                .parse()
                .with_context(|| format!("Unable to parse URL {:?}", result.cover_image))?;

            let thumbnail_url: Url = result
                .thumb
                .parse()
                .with_context(|| format!("Unable to parse thumbnail URL {:?}", result.thumb))?;

            let cover = Cover {
                url,
                thumbnail_url,
                size_px: Metadata::known((width, height)),
                format: Metadata::known(Format::Jpeg),
                source_name: SourceName::Discogs,
                source_http: Arc::clone(http),
                relevance: DISCOGS_RELEVANCE,
                rank,
            };
            results.push(cover);
        }

        Ok(results)
    }

    fn common_headers(&self) -> HeaderMap {
        let mut auth_header =
            HeaderValue::from_static(formatcp!("Discogs key={API_KEY}, secret={API_SECRET}"));
        auth_header.set_sensitive(true);
        [
            (
                HeaderName::from_static("accept"),
                HeaderValue::from_static("application/vnd.discogs.v2.discogs+json"),
            ),
            (HeaderName::from_static("authorization"), auth_header),
        ]
        .into_iter()
        .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::source::tests::{source_has_results, source_no_results};

    #[test]
    fn parse_dimensions() {
        let url = "https://i.discogs.com/abc/rs:fit/g:sm/q:90/h:600/w:593/czM6Ly9kaXNjb2dz.jpeg";
        assert_eq!(parse_image_dimensions(url), Some((593, 600)));
    }

    #[tokio::test]
    async fn has_results() {
        let _ = simple_logger::init_with_env();
        let source = Discogs;
        source_has_results(source, SourceName::Discogs).await;
    }

    #[tokio::test]
    async fn has_no_results() {
        let _ = simple_logger::init_with_env();
        let source = Discogs;
        source_no_results(source, SourceName::Discogs).await;
    }
}
