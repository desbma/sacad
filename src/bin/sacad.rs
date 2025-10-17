//! sacad main binary

use std::sync::Arc;

use anyhow::Context as _;
use clap::Parser as _;
use sacad::{SearchStatus, cl, search_and_download};

#[tokio::main]
async fn main() -> anyhow::Result<SearchStatus> {
    // Parse CL args
    let cl_args = cl::SacadArgs::parse();

    // Init logger
    simple_logger::init_with_level(cl_args.verbosity).context("Failed to setup logger")?;

    // Run
    search_and_download(
        &cl_args.output_filepath,
        Arc::new(cl_args.query),
        Arc::new(cl_args.search_opts),
        &cl_args.image_proc,
    )
    .await
}
