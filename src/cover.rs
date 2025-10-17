//! Cover

use std::{
    cmp::{self, Ord as _, max},
    collections::HashMap,
    fmt,
    fs::File,
    io::{self, BufRead, BufReader, BufWriter, Seek},
    path::Path,
    sync::Arc,
    time::Duration,
};

use anyhow::Context as _;
use heck::ToTitleCase as _;
use image::GenericImageView as _;
use typed_floats::PositiveFinite;

use crate::{
    cl::{ImageProcessingArgs, SearchOptions, SourceName},
    http,
    perceptual_hash::PerceptualHash,
    source::Relevance,
};

/// Duration after which thumbnail cache entries are evicted
pub(crate) const THUMBNAIL_MAX_AGE: Duration = Duration::from_hours(24 * 365); // One year

/// Cover metadata that can be known or uncertain
#[derive(Debug, Clone, Eq, PartialEq, Hash)]
pub(crate) enum Metadata<T> {
    /// Exact value is known
    Known(T),
    /// Value is uncertain, we only have a hint
    Uncertain(T),
}

impl<T> Metadata<T> {
    pub(crate) fn known(v: T) -> Self {
        Self::Known(v)
    }

    pub(crate) fn uncertain(v: T) -> Self {
        Self::Uncertain(v)
    }

    pub(crate) fn value_hint(&self) -> &T {
        match self {
            Metadata::Known(v) | Metadata::Uncertain(v) => v,
        }
    }

    #[expect(dead_code)]
    pub(crate) fn value(&self) -> Option<&T> {
        match self {
            Metadata::Known(v) => Some(v),
            Metadata::Uncertain(_) => None,
        }
    }
}

/// Image format
#[derive(Clone, Debug, Eq, PartialEq, Hash, strum::EnumIter)]
pub(crate) enum Format {
    /// JPEG
    Jpeg,
    /// PNG
    Png,
}

impl Format {
    /// Guess format from extension (without dot)
    pub(crate) fn from_extension(ext: &str) -> Option<Self> {
        match ext.to_lowercase().as_str() {
            "jpg" | "jpeg" => Some(Self::Jpeg),
            "png" => Some(Self::Png),
            _ => None,
        }
    }

    /// Guess format from reader
    pub(crate) fn from_reader<R>(reader: R) -> Option<Format>
    where
        R: BufRead + Seek,
    {
        match image::ImageReader::new(reader)
            .with_guessed_format()
            .ok()?
            .format()?
        {
            image::ImageFormat::Png => Some(Format::Png),
            image::ImageFormat::Jpeg => Some(Format::Jpeg),
            _ => None,
        }
    }

    /// Get canonical extension for format
    fn extension(&self) -> &'static str {
        match self {
            Format::Jpeg => "jpg",
            Format::Png => "png",
        }
    }

    /// Get image format as the image crate type
    fn to_image_format(&self) -> image::ImageFormat {
        match self {
            Format::Jpeg => image::ImageFormat::Jpeg,
            Format::Png => image::ImageFormat::Png,
        }
    }
}

/// A cover result
#[derive(Clone)]
pub(crate) struct Cover {
    /// The main cover image URL
    pub url: reqwest::Url,
    /// Thumbnail image URL
    pub thumbnail_url: reqwest::Url,
    /// Image size in pixels
    pub size_px: Metadata<(u32, u32)>,
    /// Format
    pub format: Metadata<Format>,
    /// Cover source name
    pub source_name: SourceName,
    /// Cover source HTTP client
    pub source_http: Arc<http::SourceHttpClient>,
    /// Relevance for search query
    pub relevance: Relevance,
    /// Rank is source results
    pub rank: usize,
}

impl fmt::Display for Cover {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{} #{} {}x{}{} {}",
            self.source_name.as_ref().to_title_case(),
            self.rank,
            self.size_px.value_hint().0,
            self.size_px.value_hint().1,
            match self.size_px {
                Metadata::Known(_) => "",
                Metadata::Uncertain(_) => "[?]",
            },
            self.url
        )
    }
}

impl Cover {
    /// Download thumbnail and compute perceptual hash
    pub(crate) async fn perceptual_hash(&self) -> anyhow::Result<PerceptualHash> {
        // Download
        let buf = self
            .source_http
            .download_thumbnail(self.thumbnail_url.clone())
            .await
            .with_context(|| format!("Failed to download thumbnail {}", self.thumbnail_url))?;

        log::debug!("Computing perceptual hash for {self}");
        let hash =
            tokio::task::spawn_blocking(move || PerceptualHash::from_image_buffer(&buf)).await??;
        Ok(hash)
    }

    /// Download cover to local file
    pub(crate) async fn download(
        self,
        output: &Path,
        image_proc: &ImageProcessingArgs,
        seach_opts: &SearchOptions,
    ) -> anyhow::Result<()> {
        log::debug!("Downloading {self}");

        // Download to temporary file
        let mut tmp_file = tempfile::tempfile()?;
        let mut writer = BufWriter::new(tmp_file);
        self.source_http
            .download_cover(self.url.clone(), &mut writer)
            .await
            .with_context(|| format!("Failed to download cover {}", self.url))?;
        tmp_file = writer.into_inner()?;
        tmp_file.rewind()?;

        // Get format if unsure
        let cover_format = match self.format {
            Metadata::Known(f) => f,
            Metadata::Uncertain(uf) => {
                let mut reader = BufReader::new(tmp_file);
                let f = Format::from_reader(&mut reader).unwrap_or(uf);
                tmp_file = reader.into_inner();
                tmp_file.rewind()?;
                f
            }
        };

        // Get size if unsure
        let size_px = match self.size_px {
            Metadata::Known(f) => f,
            Metadata::Uncertain(_) => {
                let mut reader = BufReader::new(tmp_file);
                let img = image::load(&mut reader, cover_format.to_image_format())?;
                tmp_file = reader.into_inner();
                tmp_file.rewind()?;
                img.dimensions()
            }
        };
        let max_size = max(size_px.0, size_px.1);

        let output_format = output
            .extension()
            .and_then(|ext| ext.to_str())
            .and_then(Format::from_extension)
            .unwrap_or_else(|| {
                log::warn!(
                    "Unable to guess output format from filepath {output:?}, defaulting to JPEG"
                );
                Format::Jpeg
            });

        let need_format_change = (cover_format != output_format) && !image_proc.preserve_format;
        let need_resize = !seach_opts.matches_max_size(max_size);

        let output_filepath =
            if !need_resize && (cover_format != output_format) && image_proc.preserve_format {
                // Change output extension
                output.with_extension(cover_format.extension())
            } else {
                output.to_path_buf()
            };

        if need_format_change || need_resize {
            // Convert
            let reader = BufReader::new(tmp_file);
            let mut img = image::load(reader, cover_format.to_image_format())?;
            if need_resize {
                img = img.resize(
                    seach_opts.size,
                    seach_opts.size,
                    image::imageops::FilterType::Lanczos3,
                );
                // TODO unsharp?
            }
            img.save_with_format(&output_filepath, output_format.to_image_format())?;
        } else {
            // Just copy
            let mut dest = File::create(&output_filepath)?;
            io::copy(&mut tmp_file, &mut dest)?;
        }

        // Crunch
        if let Format::Png = output_format {
            log::info!("Crunching PNG file {output_filepath:?}...");
            tokio::task::spawn_blocking(move || {
                let options = oxipng::Options::from_preset(2);
                match oxipng::optimize(
                    &oxipng::InFile::Path(output_filepath.clone()),
                    &oxipng::OutFile::from_path(output_filepath.clone()),
                    &options,
                ) {
                    #[expect(clippy::cast_precision_loss)]
                    Ok((size_before, size_after)) => {
                        let size_delta = size_before.checked_sub(size_after).unwrap_or_default();
                        log::debug!(
                            "PNG crunching saved {} bytes ({:.02}%%)",
                            size_delta,
                            100.0 * size_delta as f64 / size_before as f64
                        );
                    }
                    Err(err) => {
                        log::warn!("Failed to crunch PNG file {output_filepath:?}: {err}");
                    }
                }
            })
            .await?;
        }

        Ok(())
    }

    /// Get key to use type in hash tables
    pub(crate) fn key(&self) -> CoverKey {
        CoverKey {
            url: self.url.clone(),
            source_name: self.source_name,
        }
    }
}

/// Simplified cover type to use as key in hash tables
#[derive(Clone, Debug, Eq, PartialEq, Hash)]
pub(crate) struct CoverKey {
    /// Cover URL
    url: reqwest::Url,
    /// Cover source
    source_name: SourceName,
}

/// Info about cover perceptual hashes for comparison to reference cover
pub(crate) struct SearchReference {
    /// Reference cover hash
    pub reference: PerceptualHash,
    /// Hashes of all covers
    pub hashes: HashMap<CoverKey, PerceptualHash>,
}

/// How to compare two covers
pub(crate) enum CompareMode<'a> {
    /// We are only looking for the reference cover, so don't care about size for example
    Reference,
    /// Normal comparison for search result sorting
    Search {
        /// Search query
        search_opts: &'a SearchOptions,
        /// Reference info
        reference: &'a Option<SearchReference>,
    },
}

/// Compare two covers
pub(crate) fn compare(a: &Cover, b: &Cover, mode: &CompareMode) -> cmp::Ordering {
    // Prefer square covers
    #[expect(clippy::unwrap_used)]
    let ratio_a = PositiveFinite::<f64>::try_from(
        (f64::from(a.size_px.value_hint().0) / f64::from(a.size_px.value_hint().1) - 1.0).abs(),
    )
    .unwrap();
    #[expect(clippy::unwrap_used)]
    let ratio_b = PositiveFinite::<f64>::try_from(
        (f64::from(b.size_px.value_hint().0) / f64::from(b.size_px.value_hint().1) - 1.0).abs(),
    )
    .unwrap();
    if (ratio_a - ratio_b).abs() > 0.15 {
        return ratio_b.cmp(&ratio_a);
    }

    let avg_size_a = u32::midpoint(a.size_px.value_hint().0, a.size_px.value_hint().1);
    let avg_size_b = u32::midpoint(b.size_px.value_hint().0, b.size_px.value_hint().1);
    if let CompareMode::Search {
        search_opts: query,
        reference,
    } = mode
    {
        // Prefer similar to reference
        if let Some(SearchReference { reference, hashes }) = reference {
            let a_similar_to_ref = hashes
                .get(&a.key())
                .is_some_and(|h| h.is_similar(reference));
            let b_similar_to_ref = hashes
                .get(&b.key())
                .is_some_and(|h| h.is_similar(reference));
            if a_similar_to_ref != b_similar_to_ref {
                return a_similar_to_ref.cmp(&b_similar_to_ref);
            }
        }

        // Prefer size above target size
        match (avg_size_a.cmp(&query.size), avg_size_b.cmp(&query.size)) {
            (cmp::Ordering::Less, cmp::Ordering::Equal | cmp::Ordering::Greater) => {
                return cmp::Ordering::Less;
            }
            (cmp::Ordering::Equal | cmp::Ordering::Greater, cmp::Ordering::Less) => {
                return cmp::Ordering::Greater;
            }
            _ => {}
        }

        // If both below target size, prefer closest
        if (avg_size_a != avg_size_b) && (avg_size_a < query.size) && (avg_size_b < query.size) {
            return avg_size_a.cmp(&avg_size_b);
        }
    }

    // Prefer covers of better relevance
    if a.relevance != b.relevance {
        return a.relevance.cmp(&b.relevance);
    }

    // Prefer best ranked cover
    if a.rank != b.rank {
        return b.rank.cmp(&a.rank);
    }

    // Prefer covers with reliable metadata
    match (&a.size_px, &b.size_px) {
        (Metadata::Known(_), Metadata::Uncertain(_)) => return cmp::Ordering::Greater,
        (Metadata::Uncertain(_), Metadata::Known(_)) => return cmp::Ordering::Less,
        _ => {}
    }
    match (&a.format, &b.format) {
        (Metadata::Known(_), Metadata::Uncertain(_)) => return cmp::Ordering::Greater,
        (Metadata::Uncertain(_), Metadata::Known(_)) => return cmp::Ordering::Less,
        _ => {}
    }

    if let CompareMode::Search { search_opts, .. } = mode {
        // Prefer covers closest to the target size
        if avg_size_a != avg_size_b {
            return avg_size_b
                .abs_diff(search_opts.size)
                .cmp(&avg_size_a.abs_diff(search_opts.size));
        }
    }

    // Prefer PNG covers
    match (a.format.value_hint(), b.format.value_hint()) {
        (Format::Jpeg, Format::Png) => return cmp::Ordering::Less,
        (Format::Png, Format::Jpeg) => return cmp::Ordering::Greater,
        _ => {}
    }

    // Prefer exactly square covers
    ratio_b.cmp(&ratio_a)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn perceptual_hash() {
        let urls = [
            "https://is4-ssl.mzstatic.com/image/thumb/Features6/v4/ee/bd/69/eebd6962-9b25-c177-c175-b3b3e641a29d/dj.edqjfvzd.jpg/828x0w.jpg",
            "http://www.jesus-is-savior.com/Evils%20in%20America/Rock-n-Roll/highway_to_hell-large.jpg",
            "https://i.discogs.com/nBZXSMXtM2aj2WNtaLm61eGeKJlqLKfjoY8EtiUjwHQ/rs:fit/g:sm/q:90/h:600/w:593/czM6Ly9kaXNjb2dz/LWRhdGFiYXNlLWlt/YWdlcy9SLTU0NjY1/ODYtMTM5NDA5Mzcz/Ny0xMjYyLmpwZWc.jpeg",
        ];
        let img_buffers = futures::future::join_all(urls.iter().map(|url| async {
            let resp = reqwest::get(*url)
                .await
                .unwrap()
                .error_for_status()
                .unwrap();
            resp.bytes().await.unwrap().to_vec()
        }))
        .await;
        let hashes = img_buffers
            .iter()
            .map(|b| PerceptualHash::from_image_buffer(b))
            .map(Result::unwrap)
            .collect::<Vec<_>>();
        assert!(hashes[0].is_similar(&hashes[1]));
        assert!(hashes[1].is_similar(&hashes[0]));
        assert!(!hashes[0].is_similar(&hashes[2]));
        assert!(!hashes[1].is_similar(&hashes[2]));
        assert!(!hashes[2].is_similar(&hashes[0]));
        assert!(!hashes[2].is_similar(&hashes[1]));
    }
}
