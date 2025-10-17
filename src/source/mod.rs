//! Cover sources

mod itunes;

use std::time::Duration;

use crate::{
    cl::{CoverSourceName, SearchArgs},
    cover::Cover,
    http::Http,
    source::itunes::Itunes,
};

/// Cover source
#[async_trait::async_trait]
pub(crate) trait Source: Sync + Send {
    /// Search for a cover and return results
    async fn search(&self, query: &SearchArgs, http: &mut Http) -> anyhow::Result<Cover>;

    /// Get user-agent to use for all requests
    fn user_agent(&self) -> &'static str {
        concat!(env!("CARGO_PKG_NAME"), '/', env!("CARGO_PKG_VERSION"))
    }

    /// Get total timeout to use for all requests
    fn timeout(&self) -> Duration {
        Duration::from_secs(10)
    }
}

impl From<&CoverSourceName> for Box<dyn Source> {
    fn from(val: &CoverSourceName) -> Self {
        match val {
            CoverSourceName::Deezer => todo!(),
            CoverSourceName::Discogs => todo!(),
            CoverSourceName::Itunes => Box::new(Itunes),
            CoverSourceName::LastFm => todo!(),
        }
    }
}
