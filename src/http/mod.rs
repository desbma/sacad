//! Common HTTP code

use std::{fs, time::Duration};

use anyhow::Context as _;
use cache::Cache;

mod cache;

/// Per source HTTP interface
pub(crate) struct Http {
    /// Client
    client: reqwest::Client,
    /// Local cache
    cache: Cache,
}

impl Http {
    /// Create a new HTTP client
    pub(crate) fn new(cache_name: &str, ua: &str, timeout: Duration) -> anyhow::Result<Self> {
        let client = reqwest::Client::builder()
            .user_agent(ua)
            .timeout(timeout)
            .build()
            .context("Failed to create HTTP client")?;

        let dirs = directories::ProjectDirs::from("", "", env!("CARGO_PKG_NAME"))
            .ok_or_else(|| anyhow::anyhow!("Unable to compute cache directory"))?;
        let cache_dir = dirs.cache_dir();
        fs::create_dir_all(cache_dir)
            .with_context(|| format!("Failed to create dir {cache_dir:?}"))?;
        let cache_path = cache_dir.join(format!("http_{cache_name}.db"));
        let cache = Cache::new(&cache_path)
            .with_context(|| format!("Failed to open cache at {cache_path:?}"))?;

        Ok(Self { client, cache })
    }

    /// Send a GET request to URL or get it from cache, parse response as JSON
    pub(crate) async fn get_json<R>(&mut self, url: reqwest::Url) -> anyhow::Result<R>
    where
        R: serde::de::DeserializeOwned + bitcode::Encode + bitcode::DecodeOwned,
    {
        let cache_key = url.as_str().to_owned();
        if let Some(cache_hit) = self
            .cache
            .get::<_, R>(&cache_key)
            .with_context(|| format!("Cache retrieval failed for key {cache_key:?}"))?
        {
            log::trace!("Cache hit for key {cache_key:?}");
            Ok(cache_hit)
        } else {
            let response = self
                .client
                .get(url)
                .send()
                .await
                .with_context(|| format!("HTTP error for URL {cache_key:?}"))?;
            let data = response.bytes().await?;
            let r: R = serde_json::from_slice(&data)?;
            self.cache.set(&cache_key, &r)?;
            Ok(r)
        }
    }
}
