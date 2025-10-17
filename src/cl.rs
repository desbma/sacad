//! Command line interface

use std::path::PathBuf;

use clap::Parser;
use strum::VariantArray as _;

/// Command line arguments
#[derive(Parser, Debug)]
#[command(version, about)]
pub struct Args {
    /// Search options
    #[clap(flatten)]
    pub search: SearchArgs,
    /// Image conversion options
    #[clap(flatten)]
    pub image_output: ImageOutputArgs,
    /// Level of logging output
    #[clap(short, long, default_value_t = log::Level::Info)]
    pub verbosity: log::Level,
}

/// Command line arguments related to search
#[derive(Parser, Debug)]
pub struct SearchArgs {
    /// Artist to search for
    pub artist: String,
    /// Album to search for
    pub album: String,
    /// Target image size
    pub size: u32,
    /// Tolerate this percentage of size difference with the target size.
    /// Note that covers with size above or close to the target size will still be preferred if available
    #[clap(short = 't', long = "size-tolerance", default_value_t = 25)]
    pub size_tolerance_prct: u32,
    /// Cover sources to use, if not set use all of them.
    /// This option should either be the last one in the command line, or be passed immediately before positional
    /// arguments and followed by '--' (ie. `sacad -s source1 source2 -- artist album size out_filepath`)
    #[clap(short = 's', long, default_values_t = CoverSourceName::VARIANTS.to_vec())]
    pub cover_sources: Vec<CoverSourceName>,
}

/// Command line arguments related to output image processing
#[derive(Parser, Debug)]
pub struct ImageOutputArgs {
    /// Output image file path
    output_filepath: PathBuf,
    /// Preserve source image format if possible.
    /// Target format will still be prefered when sorting results
    #[clap(short, long)]
    preserve_format: bool,
    /// Convert progressive JPEG to baseline if needed.
    /// May result in bigger files and loss of quality
    #[clap(long)]
    convert_progressive_jpeg: bool,
}

/// Cover source name
#[derive(Debug, Clone, strum::EnumString, strum::VariantArray, strum::AsRefStr, strum::Display)]
#[strum(serialize_all = "lowercase")]
#[expect(missing_docs)]
pub enum CoverSourceName {
    Deezer,
    Discogs,
    Itunes,
    LastFm,
}
