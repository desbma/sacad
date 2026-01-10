//! Cover sources

mod coverartarchive;
mod deezer;
mod discogs;
mod itunes;
mod lastfm;

use std::{cmp, sync::Arc, time::Duration};

use reqwest::header::HeaderMap;

use crate::{
    cl::SourceName,
    cover::Cover,
    http::{self, SourceHttpClient},
    source::{
        coverartarchive::CoverArtArchive, deezer::Deezer, discogs::Discogs, itunes::Itunes,
        lastfm::LastFm,
    },
};

/// Duration after which source responses cache entries are evicted
pub(crate) const RESPONSE_MAX_AGE: Duration = Duration::from_hours(24 * 7); // One week

/// How precise/relevant are results from a source
#[derive(Clone, Debug, Eq, PartialEq, Hash)]
pub(crate) struct Relevance {
    /// Is the source search fuzzy?
    fuzzy: bool,
    /// Does the source return only front covers?
    only_front_covers: bool,
    /// Can the source return unrelated pictures?
    unrelated_risk: bool,
}

impl Ord for Relevance {
    fn cmp(&self, other: &Self) -> cmp::Ordering {
        match self.unrelated_risk.cmp(&other.unrelated_risk) {
            cmp::Ordering::Less => {
                return cmp::Ordering::Greater;
            }
            cmp::Ordering::Greater => {
                return cmp::Ordering::Less;
            }
            cmp::Ordering::Equal => {}
        }
        match self.only_front_covers.cmp(&other.only_front_covers) {
            cmp::Ordering::Equal => {}
            ord => {
                return ord;
            }
        }
        match self.fuzzy.cmp(&other.fuzzy) {
            cmp::Ordering::Less => cmp::Ordering::Greater,
            cmp::Ordering::Greater => cmp::Ordering::Less,
            cmp::Ordering::Equal => cmp::Ordering::Equal,
        }
    }
}

impl PartialOrd for Relevance {
    fn partial_cmp(&self, other: &Self) -> Option<cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Relevance {
    /// Return true if source results can only be the correct cover (but can be wrong size/format)
    pub(crate) fn is_reference(&self) -> bool {
        !self.fuzzy && self.only_front_covers && !self.unrelated_risk
    }

    #[cfg(test)]
    pub(crate) fn best() -> Self {
        Self {
            fuzzy: false,
            only_front_covers: true,
            unrelated_risk: false,
        }
    }

    #[cfg(test)]
    pub(crate) fn worst() -> Self {
        Self {
            fuzzy: true,
            only_front_covers: false,
            unrelated_risk: true,
        }
    }
}

/// Source error witht he source name for display
#[derive(thiserror::Error, Debug)]
#[error("Source {source} failed with error {err}")]
pub(crate) struct SourceError {
    /// Error
    #[source]
    pub err: anyhow::Error,
    /// Source name
    pub source: SourceName,
}

/// How to rate limit the requests sent by a source
pub(crate) struct RateLimit {
    /// Duration on which to apply the limit
    pub time: Duration,
    /// Maximum count of request during the time window
    pub max_count: usize,
}

/// Cover source
#[async_trait::async_trait]
pub(crate) trait Source: Sync + Send {
    /// Search for a cover and return results
    async fn search(
        &self,
        artist: &str,
        album: &str,
        http: &mut Arc<SourceHttpClient>,
    ) -> anyhow::Result<Vec<Cover>>;

    /// Get user-agent to use for all requests
    fn user_agent(&self) -> &'static str {
        http::USER_AGENT
    }

    /// Get total timeout to use for all requests
    fn timeout(&self) -> Duration {
        Duration::from_secs(10)
    }

    /// Get HTTP headers to use for all requests
    fn common_headers(&self) -> HeaderMap {
        HeaderMap::new()
    }

    /// Get HTTP rate limiting strategy
    fn rate_limit(&self) -> Option<RateLimit> {
        Some(RateLimit {
            time: Duration::from_millis(500),
            max_count: 5,
        })
    }
}

impl From<&SourceName> for Box<dyn Source> {
    fn from(val: &SourceName) -> Self {
        match val {
            SourceName::CoverArtArchive => Box::new(CoverArtArchive),
            SourceName::Deezer => Box::new(Deezer),
            SourceName::Discogs => Box::new(Discogs),
            SourceName::Itunes => Box::new(Itunes),
            SourceName::LastFm => Box::new(LastFm),
        }
    }
}

/// Remove chars in input string
fn remove_chars<S, F>(s: S, filter: F) -> String
where
    S: AsRef<str>,
    F: Fn(&char) -> bool,
{
    s.as_ref().chars().filter(filter).collect()
}

/// Normalize string by converting to lowercase and replace accentuated chars
fn normalize<S>(s: S) -> String
where
    S: AsRef<str>,
{
    s.as_ref()
        .chars()
        .flat_map(|oc| {
            let mut nc = None;
            unicode_normalization::char::decompose_canonical(oc, |c| {
                nc.get_or_insert(c);
            });
            nc.unwrap_or(oc).to_lowercase()
        })
        .collect()
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;

    #[test]
    fn normalize() {
        assert_eq!(super::normalize("AÀh' JÉeêé"), "aah' jeeee");
    }

    pub(crate) async fn source_has_results<S>(source: S, source_name: SourceName)
    where
        S: Source,
    {
        let mut http = Arc::new(
            SourceHttpClient::new(
                source_name,
                source.user_agent(),
                source.timeout(),
                source.common_headers(),
                source.rate_limit().as_ref(),
            )
            .unwrap(),
        );
        assert!(
            !source
                .search("Michael Jackson", "Thriller", &mut http)
                .await
                .unwrap()
                .is_empty(),
        );
        assert!(
            !source
                .search("Björk", "Vespertine", &mut http)
                .await
                .unwrap()
                .is_empty(),
        );
    }

    pub(crate) async fn source_no_results<S>(source: S, source_name: SourceName)
    where
        S: Source,
    {
        let mut http = Arc::new(
            SourceHttpClient::new(
                source_name,
                source.user_agent(),
                source.timeout(),
                source.common_headers(),
                source.rate_limit().as_ref(),
            )
            .unwrap(),
        );
        assert!(
            source
                .search("mlkjjkhjklhlkjhlk", "mlkjjkhjklhlkjhlk", &mut http)
                .await
                .unwrap()
                .is_empty(),
        );
    }
}
