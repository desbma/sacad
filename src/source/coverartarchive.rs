//! Cover Art Archive cover source
//
// Searches releases via the `MusicBrainz` API, then fetches cover art from `coverartarchive.org`
// See: https://musicbrainz.org/doc/MusicBrainz_API and https://musicbrainz.org/doc/Cover_Art_Archive/API

use std::{sync::Arc, time::Duration};

use anyhow::Context as _;
use reqwest::Url;

use crate::{
    cl::SourceName,
    cover::{Cover, Format, Metadata},
    http::SourceHttpClient,
    source::{self, RateLimit, Source, normalize},
};

/// Cover Art Archive cover source
pub(crate) struct CoverArtArchive;

#[derive(Debug, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "kebab-case")]
struct MusicBrainzReleaseSearchResponse {
    releases: Vec<MusicBrainzRelease>,
}

#[derive(Debug, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "kebab-case")]
struct MusicBrainzRelease {
    id: String,
    title: String,
    artist_credit: Vec<ArtistCredit>,
}

impl MusicBrainzRelease {
    /// Check if the release is a fuzzy match (artist/album don't match exactly)
    fn is_fuzzy_match(&self, nartist: &str, nalbum: &str) -> bool {
        let release_album = normalize(&self.title);
        (release_album != nalbum)
            || !self
                .artist_credit
                .iter()
                .map(|c| normalize(&c.name))
                .any(|ac| ac == nartist)
    }
}

#[derive(Debug, serde::Serialize, serde::Deserialize)]
struct ArtistCredit {
    name: String,
}

#[derive(Debug, serde::Serialize, serde::Deserialize)]
struct CoverArtResponse {
    images: Vec<CoverArtImage>,
}

#[derive(Debug, serde::Serialize, serde::Deserialize)]
struct CoverArtImage {
    image: String,
    front: bool,
    thumbnails: CoverArtThumbnails,
}

#[derive(Debug, serde::Serialize, serde::Deserialize)]
struct CoverArtThumbnails {
    #[serde(rename = "250")]
    small: Option<String>,
    #[serde(rename = "500")]
    medium: Option<String>,
    #[serde(rename = "1200")]
    large: Option<String>,
}

/// Getter function for thumbnail URL by size
type ThumbnailGetter = fn(&CoverArtThumbnails) -> Option<&String>;

/// Thumbnail sizes available from Cover Art Archive
const THUMBNAIL_SIZES: &[(u32, ThumbnailGetter)] = &[
    (250, |t| t.small.as_ref()),
    (500, |t| t.medium.as_ref()),
    (1200, |t| t.large.as_ref()),
];

/// Default relevance for Cover Art Archive covers
const COVERARTARCHIVE_RELEVANCE: source::Relevance = source::Relevance {
    fuzzy: false,
    only_front_covers: true,
    unrelated_risk: false,
};

#[async_trait::async_trait]
impl Source for CoverArtArchive {
    async fn search(
        &self,
        artist: &str,
        album: &str,
        http: &mut Arc<SourceHttpClient>,
    ) -> anyhow::Result<Vec<Cover>> {
        let nartist = normalize(artist);
        let nalbum = normalize(album);

        let releases = self.musicbrainz_releases(&nartist, &nalbum, http).await?;

        let mut results = Vec::new();
        for (rank, release) in releases.into_iter().enumerate() {
            let is_fuzzy = release.is_fuzzy_match(&nartist, &nalbum);
            if let Ok(covers) = self.release_covers(&release.id, rank, is_fuzzy, http).await {
                results.extend(covers);
            }
        }

        Ok(results)
    }

    fn rate_limit(&self) -> Option<RateLimit> {
        // https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting
        Some(RateLimit {
            time: Duration::from_secs(1),
            max_count: 1,
        })
    }
}

impl CoverArtArchive {
    /// Search for MB releases matching artist and album
    async fn musicbrainz_releases(
        &self,
        artist: &str,
        album: &str,
        http: &mut Arc<SourceHttpClient>,
    ) -> anyhow::Result<Vec<MusicBrainzRelease>> {
        // https://musicbrainz.org/doc/MusicBrainz_API/Search#Release
        let query = format!("artist:\"{artist}\" AND release:\"{album}\"");
        // Note: set a low result limit because following requests are slow due to rate limit
        // Note: pagination is also available
        let url_params = [("query", query.as_str()), ("limit", "8"), ("fmt", "json")];

        #[expect(clippy::unwrap_used)]
        let search_url =
            Url::parse_with_params("https://musicbrainz.org/ws/2/release", url_params).unwrap();

        let resp: MusicBrainzReleaseSearchResponse = http.get_json(search_url).await?;
        Ok(resp.releases)
    }

    /// Fetch cover art from Cover Art Archive for a given release MBID
    async fn release_covers(
        &self,
        mbid: &str,
        rank: usize,
        is_fuzzy: bool,
        http: &mut Arc<SourceHttpClient>,
    ) -> anyhow::Result<Vec<Cover>> {
        #[expect(clippy::unwrap_used)]
        let caa_url = Url::parse(&format!("https://coverartarchive.org/release/{mbid}")).unwrap();

        let resp: CoverArtResponse = http.get_json(caa_url).await?;

        let mut covers = Vec::new();
        for image in resp.images.into_iter().filter(|img| img.front) {
            let thumbnails: Vec<_> = THUMBNAIL_SIZES
                .iter()
                .filter_map(|(size, thumbnail_url)| {
                    thumbnail_url(&image.thumbnails).map(|u| (size, u))
                })
                .filter_map(|(s, u)| u.parse::<Url>().ok().map(|u| (s, u)))
                .collect();
            let Some(thumbnail_url) = thumbnails
                .iter()
                .min_by_key(|(s, _u)| s)
                .map(|(_s, u)| u)
                .cloned()
            else {
                continue;
            };

            let relevance = source::Relevance {
                fuzzy: is_fuzzy,
                ..COVERARTARCHIVE_RELEVANCE
            };
            for (size, url) in thumbnails {
                covers.push(Cover {
                    url,
                    thumbnail_url: thumbnail_url.clone(),
                    size_px: Metadata::known((*size, *size)),
                    format: Metadata::known(Format::Jpeg),
                    source_name: SourceName::CoverArtArchive,
                    source_http: Arc::clone(http),
                    relevance: relevance.clone(),
                    rank,
                });
            }

            let main_url: Url = image.image.parse().context("Failed to parse image URL")?;
            covers.push(Cover {
                url: main_url,
                thumbnail_url,
                size_px: Metadata::uncertain((900, 900)),
                format: Metadata::uncertain(Format::Png),
                source_name: SourceName::CoverArtArchive,
                source_http: Arc::clone(http),
                relevance,
                rank,
            });
        }

        Ok(covers)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::source::tests::{source_has_results, source_no_results};

    #[tokio::test]
    async fn has_results() {
        let _ = simple_logger::init_with_env();
        let source = CoverArtArchive;
        source_has_results(source, SourceName::CoverArtArchive).await;
    }

    #[tokio::test]
    async fn has_no_results() {
        let _ = simple_logger::init_with_env();
        let source = CoverArtArchive;
        source_no_results(source, SourceName::CoverArtArchive).await;
    }
}
