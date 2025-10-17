//! Last.fm cover source

// See https://www.last.fm/api/show/album.getInfo

use std::{
    collections::{HashMap, HashSet},
    sync::{Arc, LazyLock},
};

use anyhow::Context as _;
use reqwest::{StatusCode, Url};

use crate::{
    cl::SourceName,
    cover::{Cover, Format, Metadata},
    http::SourceHttpClient,
    source::{self, Source, normalize},
};

/// Last.fm cover source
pub(crate) struct LastFm;

#[derive(Debug, serde::Serialize, serde::Deserialize)]
struct Response {
    album: Vec<ResponseAlbum>,
}

#[derive(Debug, serde::Serialize, serde::Deserialize)]
struct ResponseAlbum {
    image: Vec<ResponseImage>,
}

#[derive(Debug, serde::Serialize, serde::Deserialize)]
struct ResponseImage {
    #[serde(rename = "$value", default)]
    url: String,
    #[serde(rename = "@size", default)]
    size: String,
}

/// Relevance for Last.fm source
const LASTFM_RELEVANCE: source::Relevance = source::Relevance {
    fuzzy: false,
    only_front_covers: true,
    unrelated_risk: false,
};

/// Last.fm API key
const API_KEY: &str = "2410a53db5c7490d0f50c100a020f359";

/// Map of image size strings to size in pixels
static SIZE: LazyLock<HashMap<&str, Metadata<(u32, u32)>>> = LazyLock::new(|| {
    // For mega, this is often between 600 and 900, sometimes more or less (ie 300/1200)
    [
        ("small", Metadata::known((34, 34))),
        ("medium", Metadata::known((64, 64))),
        ("large", Metadata::known((174, 174))),
        ("extralarge", Metadata::known((300, 300))),
        ("mega", Metadata::uncertain((600, 600))),
        ("", Metadata::uncertain((600, 600))),
    ]
    .into_iter()
    .collect()
});

#[async_trait::async_trait]
impl Source for LastFm {
    async fn search(
        &self,
        artist: &str,
        album: &str,
        http: &mut Arc<SourceHttpClient>,
    ) -> anyhow::Result<Vec<Cover>> {
        let nartist = normalize(artist);
        let nalbum = normalize(album);
        let url_params = [
            ("method", "album.getinfo"),
            ("api_key", API_KEY),
            ("artist", &nartist),
            ("album", &nalbum),
        ];
        #[expect(clippy::unwrap_used)] // base URL is absolute
        let search_url =
            Url::parse_with_params("https://ws.audioscrobbler.com/2.0/", url_params).unwrap();
        let resp: Response = match http.get_xml(search_url).await {
            Ok(resp) => resp,
            Err(err)
                if err
                    .downcast_ref::<reqwest::Error>()
                    .and_then(reqwest::Error::status)
                    .is_some_and(|s| s == StatusCode::NOT_FOUND) =>
            {
                // API returns 404 for unknown albums
                return Ok(vec![]);
            }
            Err(err) => return Err(err),
        };
        let mut prev_images = HashSet::new();
        let mut results = Vec::new();
        for (rank, result) in resp.album.into_iter().enumerate() {
            let Some::<Url>(thumbnail_url) = result
                .image
                .iter()
                .min_by_key(|i| {
                    SIZE.get(i.size.as_str())
                        .map_or(&u32::MAX, |m| &m.value_hint().0)
                        .to_owned()
                })
                .and_then(|i| i.url.parse().ok())
            else {
                continue;
            };
            for image in result.image {
                if image.url.trim().is_empty() {
                    continue;
                }

                let Some(size_px) = SIZE.get(image.size.as_str()).cloned() else {
                    continue;
                };

                let url: Url = image
                    .url
                    .parse()
                    .with_context(|| format!("Unable to parse URL {:?}", image.url))?;

                if prev_images.contains(&url) {
                    continue;
                }
                // Keep URL to detect fake higher resolution images which have the same URL
                prev_images.insert(url.clone());

                let Some(format) = url
                    .as_str()
                    .rsplit_once('.')
                    .and_then(|(_, ext)| Format::from_extension(ext))
                else {
                    continue;
                };

                let cover = Cover {
                    url,
                    thumbnail_url: thumbnail_url.clone(),
                    size_px,
                    format: Metadata::known(format),
                    source_name: SourceName::LastFm,
                    source_http: Arc::clone(http),
                    relevance: LASTFM_RELEVANCE,
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
        let source = LastFm;
        source_has_results(source, SourceName::LastFm).await;
    }

    #[tokio::test]
    async fn has_no_results() {
        let _ = simple_logger::init_with_env();
        let source = LastFm;
        source_no_results(source, SourceName::LastFm).await;
    }
}
