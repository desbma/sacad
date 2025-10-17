//! Internal API exposed for sacad binaries

use std::sync::Arc;

use anyhow::Context as _;

use crate::{
    cl::{ImageOutputArgs, SearchArgs},
    http::Http,
    source::Source,
};

pub mod cl;
mod cover;
mod http;
mod source;

/// Search for a cover, sort results, and download the first one that succeeds
pub async fn search_and_download(
    search: SearchArgs,
    output: ImageOutputArgs,
) -> anyhow::Result<()> {
    // Search
    let search = Arc::new(search);
    let mut sources_searches = Vec::with_capacity(search.cover_sources.len());
    for source_name in &search.cover_sources {
        let source: Box<dyn Source> = source_name.into();
        let mut http = Http::new(source_name.as_ref(), source.user_agent(), source.timeout())
            .context("Failed to initialize HTTP")?;
        let search = Arc::clone(&search);
        sources_searches.push(tokio::spawn(async move {
            source.search(&search, &mut http).await
        }));
    }
    let mut results: Vec<_> = futures::future::join_all(sources_searches)
        .await
        .into_iter()
        .filter_map(|res| {
            res.inspect_err(|err| {
                log::error!("Failed to get source search results: {err:#}");
            })
            .ok()
        })
        .filter_map(|res| {
            res.inspect_err(|err| {
                log::error!("Source failed with error: {err:#}");
            })
            .ok()
        })
        .collect();

    // Sort
    cover::sort(&mut results, &search);

    // Download
    for result in results {
        match result.download(&output) {
            Ok(()) => return Ok(()),
            Err(err) => {
                log::error!("Download of {result} failed: {err:#}");
            }
        }
    }

    log::warn!("No cover to download");

    Ok(())
}
