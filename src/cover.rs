//! Cover

use std::fmt;

use crate::cl::{ImageOutputArgs, SearchArgs};

/// A cover result
pub(crate) struct Cover {
    /// The main cover image URL
    url: reqwest::Url,
}

impl fmt::Display for Cover {
    fn fmt(&self, _f: &mut fmt::Formatter<'_>) -> fmt::Result {
        todo!()
    }
}

impl Cover {
    /// Download cover to local file
    pub(crate) fn download(&self, _output: &ImageOutputArgs) -> anyhow::Result<()> {
        todo!()
    }
}

/// Sort covers, with most relevant first
pub(crate) fn sort(_results: &mut Vec<Cover>, _search: &SearchArgs) {
    todo!()
}
