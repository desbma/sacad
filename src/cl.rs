//! Command line interface

use std::path::PathBuf;

use clap::Parser;
use strum::VariantArray as _;

/// Command line arguments for `sacad` binary
#[derive(Parser, Debug)]
#[command(version, about)]
pub struct SacadArgs {
    /// Search query
    #[clap(flatten)]
    pub query: SearchQuery,
    /// Search options
    #[clap(flatten)]
    pub search_opts: SearchOptions,
    /// Output image file path
    pub output_filepath: PathBuf,
    /// Image conversion options
    #[clap(flatten)]
    pub image_proc: ImageProcessingArgs,
    /// Level of logging output
    #[clap(short, long, default_value_t = log::Level::Info)]
    pub verbosity: log::Level,
}

/// Command line arguments for `sacad_r` binary
#[derive(Parser, Debug)]
#[command(version, about)]
pub struct SacadRecursiveArgs {
    /// Music library directory to recursively analyze
    pub lib_root_dir: PathBuf,
    /// Search options
    #[clap(flatten)]
    pub search_opts: SearchOptions,
    /// Cover image path pattern.
    /// {artist} and {album} are replaced by their tag value.
    /// You can set an absolute path, otherwise destination
    /// directory is relative to the audio files.
    /// Use single character '+' to embed JPEG into audio files.
    #[clap(value_parser = CoverOutput::from_arg)]
    pub output: CoverOutput,
    /// Ignore existing covers and force search and download for all files
    #[clap(short, long)]
    pub ignore_existing: bool,
    /// Image conversion options
    #[clap(flatten)]
    pub image_proc: ImageProcessingArgs,
    /// Level of logging output
    #[clap(short, long, default_value_t = log::Level::Info)]
    pub verbosity: log::Level,
}

/// Cover output destination
#[derive(Clone, Debug)]
pub enum CoverOutput {
    /// Cover will be embedded in audio file(s)
    Embed,
    /// Cover will be named according to this pattern in the album directory
    Pattern(CoverOutputPattern<String>),
}

impl CoverOutput {
    #[expect(clippy::unnecessary_wraps)]
    fn from_arg(s: &str) -> Result<Self, std::convert::Infallible> {
        if s == "+" {
            Ok(CoverOutput::Embed)
        } else {
            Ok(CoverOutput::Pattern(CoverOutputPattern(s.to_owned())))
        }
    }
}

/// A file path with replaceable tag patterns
#[derive(Clone, Debug)]
pub struct CoverOutputPattern<S>(pub S);

/// Command line arguments related to the search query
#[derive(Parser, Debug)]
pub struct SearchQuery {
    /// Artist to search for
    pub artist: String,
    /// Album to search for
    pub album: String,
}

/// Command line arguments related to search options
#[derive(Parser, Debug)]
pub struct SearchOptions {
    /// Target image size
    pub size: u32,
    /// Tolerate this percentage of size difference with the target size.
    /// Note that covers with size above or close to the target size will still be preferred if available
    #[clap(short = 't', long = "size-tolerance", default_value_t = 25)]
    pub size_tolerance_prct: u32,
    /// Cover sources to use, if not set use all of them.
    /// Use multiple times to search from several sources.
    #[clap(short = 's', long, default_values_t = SourceName::VARIANTS.to_vec())]
    pub cover_sources: Vec<SourceName>,
}

impl SearchOptions {
    /// Return true if cover size matches minimum from query
    pub(crate) fn matches_min_size(&self, size: u32) -> bool {
        let min_size = self.size - self.size * self.size_tolerance_prct / 100;
        size >= min_size
    }

    /// Return true if cover size matches query or requires resize
    pub(crate) fn matches_max_size(&self, size: u32) -> bool {
        debug_assert!(self.matches_min_size(size));
        let max_size = self.size + self.size * self.size_tolerance_prct / 100;
        size <= max_size
    }
}

/// Command line arguments related to output image processing
#[derive(Parser, Debug)]
pub struct ImageProcessingArgs {
    /// Preserve source image format if possible.
    #[clap(short, long)]
    pub preserve_format: bool,
}

/// Cover source name
#[derive(
    Debug,
    Copy,
    Clone,
    Eq,
    PartialEq,
    Hash,
    strum::EnumString,
    strum::VariantArray,
    strum::AsRefStr,
    strum::Display,
)]
#[strum(serialize_all = "lowercase")]
#[expect(missing_docs)]
pub enum SourceName {
    CoverArtArchive,
    Deezer,
    Discogs,
    Itunes,
    LastFm,
}
