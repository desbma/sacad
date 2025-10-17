//! Internal API exposed for `sacad`/`sacad_r` binaries

use std::{
    cmp::min,
    collections::HashMap,
    path::Path,
    process::{ExitCode, Termination},
    sync::Arc,
};

use itertools::Itertools as _;

use crate::{
    cl::{ImageProcessingArgs, SearchOptions, SearchQuery},
    cover::{Cover, CoverKey, SearchReference},
    http::SourceHttpClient,
    perceptual_hash::PerceptualHash,
    source::{Source, SourceError},
};

pub mod cl;
mod cover;
mod http;
mod perceptual_hash;
mod source;
pub mod tags;
pub mod walk;

/// Search for covers from all sources
async fn search_all_sources(query: &Arc<SearchQuery>, search: &Arc<SearchOptions>) -> Vec<Cover> {
    let mut sources_searches = Vec::with_capacity(search.cover_sources.len());
    for source_name in search.cover_sources.iter().copied() {
        let source: Box<dyn Source> = (&source_name).into();
        let mut http = match SourceHttpClient::new(
            source_name,
            source.user_agent(),
            source.timeout(),
            source.common_headers(),
            source.rate_limit().as_ref(),
        ) {
            Ok(h) => Arc::new(h),
            Err(err) => {
                log::error!("Failed to initialize HTTP for {source_name}: {err:#}");
                continue;
            }
        };
        let query = Arc::clone(query);
        let source_task = tokio::spawn(async move {
            let results = source
                .search(&query.artist, &query.album, &mut http)
                .await
                .map_err(|err| SourceError {
                    err,
                    source: source_name,
                })?;
            Ok((results, source_name))
        });
        sources_searches.push(source_task);
    }

    futures::future::join_all(sources_searches)
        .await
        .into_iter()
        .filter_map(|res| {
            res.inspect_err(|err| {
                log::error!("Failed to get source search results: {err:#}");
            })
            .ok()
        })
        .filter_map(|res: anyhow::Result<_>| {
            res.inspect_err(|err| {
                log::error!("{err:#}");
            })
            .map(|(res, source_name)| {
                log::debug!(
                    "Source {} results:\n{}",
                    source_name,
                    res.iter()
                        .map(ToString::to_string)
                        .collect::<Vec<_>>()
                        .join("\n")
                );
                res
            })
            .ok()
        })
        .flatten()
        .collect()
}

/// Compute perceptual hash for reference cover.
async fn find_reference_hash(results: &[Cover]) -> Option<PerceptualHash> {
    let reference_candidates = results
        .iter()
        .filter(|cover| cover.relevance.is_reference())
        .sorted_by(|a, b| cover::compare(b, a, &cover::CompareMode::Reference));

    for reference_candidate in reference_candidates {
        match reference_candidate.perceptual_hash().await {
            Ok(hash) => {
                log::debug!("Reference cover is {reference_candidate}");
                return Some(hash);
            }
            Err(err) => {
                log::warn!(
                    "Failed to compute perceptual hash for reference {reference_candidate}: {err}"
                );
            }
        }
    }
    None
}

/// Compute perceptual hashes for all covers
async fn compute_perceptual_hashes(results: &[Cover]) -> HashMap<CoverKey, PerceptualHash> {
    #[expect(clippy::redundant_iter_cloned)]
    futures::future::join_all(results.iter().cloned().map(|cover| {
        tokio::spawn(async move {
            let hash = cover
                .perceptual_hash()
                .await
                .inspect_err(|err| {
                    log::warn!("Failed to compute perceptual hash for {cover}: {err:#}");
                })
                .ok()?;
            Some((cover.key(), hash))
        })
    }))
    .await
    .into_iter()
    .filter_map(Result::ok)
    .flatten()
    .collect()
}

/// Status of successful search operation
pub enum SearchStatus {
    /// A result was found and downloaded
    Found,
    /// No valid result was found for given query
    NotFound,
}

impl Termination for SearchStatus {
    fn report(self) -> ExitCode {
        match self {
            SearchStatus::Found => ExitCode::SUCCESS,
            SearchStatus::NotFound => ExitCode::FAILURE,
        }
    }
}

/// Search for a cover, sort results, and download the first one that succeeds
pub async fn search_and_download(
    output: &Path,
    query: Arc<SearchQuery>,
    search_opts: Arc<SearchOptions>,
    image_proc: &ImageProcessingArgs,
) -> anyhow::Result<SearchStatus> {
    // Search
    let mut results = search_all_sources(&query, &search_opts).await;

    // Find reference
    let reference_hash = find_reference_hash(&results).await;

    // Filter by size constraint
    results.retain(|cover| {
        let size = min(cover.size_px.value_hint().0, cover.size_px.value_hint().1);
        search_opts.matches_min_size(size)
    });

    // Build search reference with perceptual hashes if applicable
    let reference = if let Some(reference_hash) = reference_hash {
        let hashes = compute_perceptual_hashes(&results).await;
        Some(SearchReference {
            reference: reference_hash,
            hashes,
        })
    } else {
        None
    };

    // Sort
    results.sort_unstable_by(|a, b| {
        cover::compare(
            b,
            a,
            &cover::CompareMode::Search {
                search_opts: &search_opts,
                reference: &reference,
            },
        )
    });

    log::debug!("Sorted results:\n{}", results.iter().join("\n"));

    // Download
    for result in results {
        match result.download(output, image_proc, &search_opts).await {
            Ok(()) => return Ok(SearchStatus::Found),
            Err(err) => {
                log::error!("Cover download failed: {err:#}");
            }
        }
    }

    log::warn!(
        "No cover to download for artist {:?} and album {:?}",
        query.artist,
        query.album
    );
    Ok(SearchStatus::NotFound)
}
