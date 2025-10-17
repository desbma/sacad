//! placeholder

use anyhow::Context as _;
use clap::Parser as _;
use sacad::{cl, search_and_download};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Parse CL args
    let cl_args = cl::Args::parse();

    // Init logger
    simple_logger::init_with_level(cl_args.verbosity).context("Failed to setup logger")?;

    // Run
    search_and_download(cl_args.search, cl_args.image_output).await
}
