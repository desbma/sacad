//! Common HTTP code

use std::{
    collections::{HashMap, hash_map},
    fmt,
    io::Write,
    num::NonZeroUsize,
    sync::{Arc, LazyLock},
    time::{Duration, Instant},
};

use anyhow::Context as _;
use cache::Cache;
use const_format::formatcp;
use futures_util::StreamExt as _;
use parking_lot::{Mutex, RwLock};
use reqwest::{IntoUrl, Url, header::HeaderMap};

use crate::{
    cl::SourceName,
    cover,
    source::{self, RateLimit},
};

mod cache;

/// Default user agent unless overriden by source
pub(crate) const USER_AGENT: &str = formatcp!(
    "{}/{} (https://github.com/desbma/sacad)",
    env!("CARGO_PKG_NAME"),
    env!("CARGO_PKG_VERSION")
);

/// Cache for a source API responses
type ApiCache = Cache<cache::Lz4Compressor>;
/// Cache for thumbnails
type ThumbnailCache = Cache<cache::NullCompressor>;

/// Per source HTTP interface
pub(crate) struct SourceHttpClient {
    /// Client
    client: reqwest::Client,
    /// Local source API response cache
    api_cache: Arc<ApiCache>,
    /// Local thumbnail cache
    thumbnail_cache: Arc<ThumbnailCache>,
    /// Rate limit state
    rate_limit: RateLimitState,
}

/// Per source http caches
/// This is needed because we can have at most one per process
#[expect(clippy::type_complexity)]
static SOURCE_CACHES: LazyLock<RwLock<HashMap<SourceName, (Arc<ApiCache>, Arc<ThumbnailCache>)>>> =
    LazyLock::new(RwLock::default);

impl SourceHttpClient {
    /// Create a new HTTP client
    pub(crate) fn new(
        source_name: SourceName,
        ua: &str,
        timeout: Duration,
        headers: HeaderMap,
        rate_limit: Option<&RateLimit>,
    ) -> anyhow::Result<Self> {
        let client = reqwest::Client::builder()
            .user_agent(ua)
            .timeout(timeout)
            .default_headers(headers)
            .build()
            .context("Failed to create HTTP client")?;

        let (api_cache, thumbnail_cache) =
            if let Some(caches) = SOURCE_CACHES.read().get(&source_name).cloned() {
                caches
            } else {
                match SOURCE_CACHES.write().entry(source_name) {
                    hash_map::Entry::Occupied(entry) => {
                        // Another thread added the cache after our check with the read lock
                        let (api_cache, thumbnail_cache) = entry.get();
                        (Arc::clone(api_cache), Arc::clone(thumbnail_cache))
                    }
                    hash_map::Entry::Vacant(entry) => {
                        let api_cache = Arc::new(
                            Cache::new(source_name, source::RESPONSE_MAX_AGE).with_context(
                                || format!("Failed to initialize {source_name} api cache"),
                            )?,
                        );
                        let thumbnail_cache = Arc::new(
                            ThumbnailCache::new(
                                format!("{source_name}_thumbs"),
                                cover::THUMBNAIL_MAX_AGE,
                            )
                            .with_context(|| {
                                format!("Failed to initialize {source_name} thumbnail cache")
                            })?,
                        );
                        entry.insert((Arc::clone(&api_cache), Arc::clone(&thumbnail_cache)));
                        (api_cache, thumbnail_cache)
                    }
                }
            };

        let rate_limit_state = match rate_limit {
            Some(RateLimit { time, max_count }) => {
                RateLimitState::Window(Mutex::new(RateLimitWindow {
                    start: Instant::now(),
                    length: *time,
                    count: 0,
                    #[expect(clippy::unwrap_used)]
                    limit: NonZeroUsize::new(*max_count).unwrap(),
                }))
            }
            None => RateLimitState::None,
        };

        Ok(Self {
            client,
            api_cache,
            thumbnail_cache,
            rate_limit: rate_limit_state,
        })
    }

    /// Wait if needed to respect rate limit
    async fn wait(&self) {
        while let Some(time_to_sleep) = self.rate_limit.wait_for() {
            log::debug!(
                "Waiting for {:.3}s because of rate limit",
                time_to_sleep.as_secs_f64()
            );
            tokio::time::sleep(time_to_sleep).await;
        }
    }

    /// Probe URL with a HEAD request, return true if it succeeds
    /// Note: not subject to rate limit because it is used for static resources
    pub(crate) async fn head(&self, url: Url) -> anyhow::Result<bool> {
        log::trace!("HEAD {url}");
        Ok(self
            .client
            .head(url.clone())
            .send()
            .await
            .with_context(|| format!("Internal HTTP error for URL {url:?}"))?
            .status()
            .is_success())
    }

    /// Download a cover, avoiding cache
    pub(crate) async fn download_cover<U, W>(&self, url: U, mut writer: W) -> anyhow::Result<()>
    where
        U: IntoUrl,
        W: Write,
    {
        self.wait().await;

        log::debug!("Downloading {}...", url.as_str());
        let response = self
            .client
            .get(url)
            .timeout(Duration::from_secs(60))
            .send()
            .await?;

        anyhow::ensure!(
            response.status().is_success(),
            "Request failed with status: {}",
            response.status()
        );

        let mut stream = response.bytes_stream();

        while let Some(chunk) = stream.next().await {
            let chunk = chunk.context("Failed to download chunk")?;
            writer
                .write_all(&chunk)
                .context("Failed to write chunk to file")?;
        }

        Ok(())
    }

    /// Download a thumbnail, or get it from cache
    pub(crate) async fn download_thumbnail<U>(&self, url: U) -> anyhow::Result<Vec<u8>>
    where
        U: AsRef<str> + IntoUrl + Clone,
    {
        Ok(self
            .thumbnail_cache
            .get_or_set(url.clone(), async {
                let mut writer = Vec::new();
                self.download_cover(url, &mut writer).await?;
                Ok(writer)
            })
            .await?)
    }

    /// Send a GET request to URL or get it from cache
    async fn get_api(&self, url: Url) -> anyhow::Result<Vec<u8>> {
        log::trace!("GET {url}");
        let cache_key = url.as_str().to_owned();
        if let Some(cache_hit) = self
            .api_cache
            .get(&cache_key)
            .with_context(|| format!("Cache retrieval failed for key {cache_key:?}"))?
        {
            log::trace!("Cache hit for key {cache_key:?}");
            Ok(cache_hit)
        } else {
            self.wait().await;
            let response = self
                .client
                .get(url)
                .send()
                .await
                .with_context(|| format!("Internal HTTP error for URL {cache_key:?}"))?
                .error_for_status()
                .with_context(|| format!("HTTP error for URL {cache_key:?}"))?;
            let data = response.bytes().await?;
            self.api_cache.set(&cache_key, &data)?;
            Ok(data.into())
        }
    }

    /// Send a GET request to URL or get it from cache, parse response as JSON
    pub(crate) async fn get_json<R>(&self, url: Url) -> anyhow::Result<R>
    where
        R: serde::de::DeserializeOwned,
    {
        let data = self.get_api(url).await?;
        log::trace!("{}", String::from_utf8_lossy(&data));
        let r: R = serde_json::from_slice(&data)?;
        Ok(r)
    }

    /// Send a GET request to URL or get it from cache, parse response as XML
    pub(crate) async fn get_xml<R>(&self, url: Url) -> anyhow::Result<R>
    where
        R: fmt::Debug + serde::de::DeserializeOwned,
    {
        let data = self.get_api(url).await?;
        let data_s = str::from_utf8(&data).context("Failed to decode string")?;
        log::trace!("{data_s}");
        let r: R = quick_xml::de::from_str(data_s)?;
        Ok(r)
    }
}

/// Current state of http rate limit for a source
enum RateLimitState {
    /// No limit to enforce
    None,
    /// Current time window state and limits
    Window(Mutex<RateLimitWindow>),
}

/// Current rate limit state
struct RateLimitWindow {
    /// Start of the time window
    start: Instant,
    /// Duration of each time window
    length: Duration,
    /// Current count of requests made in the time window
    count: usize,
    /// Maximum request count to make in each time window
    limit: NonZeroUsize,
}

impl RateLimitState {
    /// Update rate limit state, and return None if request can be sent, or duration to wait
    /// If a duration is returned, this must be called again before sending any request
    fn wait_for(&self) -> Option<Duration> {
        match self {
            RateLimitState::None => None,
            RateLimitState::Window(state) => {
                let mut window_state = state.lock();
                let now = Instant::now();
                if now.saturating_duration_since(window_state.start) > window_state.length {
                    // Reset
                    window_state.start = now;
                    window_state.count = 1;
                    None
                } else if window_state.count < window_state.limit.get() {
                    window_state.count += 1;
                    None
                } else {
                    let time_to_wait = window_state.start + window_state.length - now;
                    Some(time_to_wait)
                }
            }
        }
    }
}
