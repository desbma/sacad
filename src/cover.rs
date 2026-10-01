//! Cover

use std::{
    cmp::{self, Ord as _, max, min},
    collections::HashMap,
    fmt,
    fs::File,
    io::{self, BufRead, BufReader, BufWriter, Seek},
    path::{Path, PathBuf},
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
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, strum::EnumIter)]
pub enum Format {
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
    #[must_use]
    pub fn extension(self) -> &'static str {
        match self {
            Format::Jpeg => "jpg",
            Format::Png => "png",
        }
    }

    /// Get image format as the image crate type
    fn to_image_format(self) -> image::ImageFormat {
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

    /// Download cover to local file, and return the path written
    pub(crate) async fn download(
        self,
        output: &Path,
        image_proc: &ImageProcessingArgs,
        search_opts: &SearchOptions,
    ) -> anyhow::Result<PathBuf> {
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
                let f = Format::from_reader(BufReader::new(&mut tmp_file)).unwrap_or(uf);
                tmp_file.rewind()?;
                f
            }
        };

        // Get size if unsure
        let (width, height) = match self.size_px {
            Metadata::Known(f) => f,
            Metadata::Uncertain(_) => {
                let reader = BufReader::new(&mut tmp_file);
                let img = image::load(reader, cover_format.to_image_format())?;
                tmp_file.rewind()?;
                img.dimensions()
            }
        };
        anyhow::ensure!(
            search_opts.matches_min_size(min(width, height)),
            "Cover {url} is smaller than expected ({width}x{height})",
            url = self.url
        );

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

        let need_resize = !search_opts.matches_max_size(max(width, height));
        let write_format = if image_proc.preserve_format && !need_resize {
            cover_format
        } else {
            output_format
        };

        let output_filepath = if write_format == output_format {
            output.to_path_buf()
        } else {
            // Change output extension
            output.with_extension(write_format.extension())
        };

        if need_resize || (write_format != cover_format) {
            // Convert
            let reader = BufReader::new(tmp_file);
            let mut img = image::load(reader, cover_format.to_image_format())?;
            if need_resize {
                img = img.resize(
                    search_opts.size,
                    search_opts.size,
                    image::imageops::FilterType::Lanczos3,
                );
                // TODO unsharp?
            }
            img.save_with_format(&output_filepath, write_format.to_image_format())?;
        } else {
            // Just copy
            let mut dest = File::create(&output_filepath)?;
            io::copy(&mut tmp_file, &mut dest)?;
        }

        // Crunch
        if let Format::Png = write_format {
            log::info!("Crunching PNG file {output_filepath:?}...");
            let crunch_filepath = output_filepath.clone();
            tokio::task::spawn_blocking(move || {
                let options = oxipng::Options::from_preset(2);
                match oxipng::optimize(
                    &oxipng::InFile::Path(crunch_filepath.clone()),
                    &oxipng::OutFile::from_path(crunch_filepath.clone()),
                    &options,
                ) {
                    #[expect(clippy::cast_precision_loss)]
                    Ok((size_before, size_after)) => {
                        let size_delta = size_before.saturating_sub(size_after);
                        log::debug!(
                            "PNG crunching saved {} bytes ({:.02}%%)",
                            size_delta,
                            100.0 * size_delta as f64 / size_before as f64
                        );
                    }
                    Err(err) => {
                        log::warn!("Failed to crunch PNG file {crunch_filepath:?}: {err}");
                    }
                }
            })
            .await?;
        }

        Ok(output_filepath)
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

/// Width of the aspect ratio deviation bands in which covers rank as equally square
const RATIO_DEVIATION_BAND_WIDTH: f64 = 0.15;

/// Compute how far an image size is from square, as its long side divided by its short side minus one
#[expect(clippy::unwrap_used)]
fn aspect_ratio_deviation((width, height): (u32, u32)) -> PositiveFinite<f64> {
    PositiveFinite::<f64>::try_from(
        f64::from(max(width, height)) / f64::from(min(width, height)) - 1.0,
    )
    .unwrap()
}

/// Compare two covers
pub(crate) fn compare(a: &Cover, b: &Cover, mode: &CompareMode) -> cmp::Ordering {
    // Prefer square covers, unless both are in the same aspect ratio deviation band
    let deviation_a = aspect_ratio_deviation(*a.size_px.value_hint());
    let deviation_b = aspect_ratio_deviation(*b.size_px.value_hint());
    let band =
        |deviation: PositiveFinite<f64>| (deviation.get() / RATIO_DEVIATION_BAND_WIDTH).floor();
    let band_ordering = band(deviation_b).total_cmp(&band(deviation_a));
    if band_ordering.is_ne() {
        return band_ordering;
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
    deviation_b.cmp(&deviation_a)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::source::tests::TEST_CACHE_DIR;

    fn make_cover(size_px: (u32, u32), format: Format) -> Cover {
        Cover {
            url: reqwest::Url::parse("https://example.com/cover.jpg").unwrap(),
            thumbnail_url: reqwest::Url::parse("https://example.com/thumb.jpg").unwrap(),
            size_px: Metadata::known(size_px),
            format: Metadata::known(format),
            source_name: SourceName::Deezer,
            source_http: Arc::new(
                http::SourceHttpClient::new(
                    SourceName::Deezer,
                    http::USER_AGENT,
                    Duration::from_secs(10),
                    reqwest::header::HeaderMap::new(),
                    None,
                    TEST_CACHE_DIR.path(),
                )
                .unwrap(),
            ),
            relevance: Relevance::best(),
            rank: 1,
        }
    }

    fn make_search_opts(size: u32) -> SearchOptions {
        SearchOptions {
            size,
            size_tolerance_prct: 25,
            cover_sources: vec![SourceName::Deezer],
        }
    }

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

    mod compare {
        use itertools::iproduct;

        use super::*;

        /// Assert that `compare` prefers the first cover over the second, in both argument orders
        #[track_caller]
        fn assert_preferred(preferred: &Cover, other: &Cover, mode: &CompareMode) {
            assert_eq!(compare(preferred, other, mode), cmp::Ordering::Greater);
            assert_eq!(compare(other, preferred, mode), cmp::Ordering::Less);
        }

        #[test]
        fn prefer_square_covers() {
            let square = make_cover((600, 600), Format::Jpeg);
            let wide = make_cover((800, 400), Format::Jpeg);
            assert_preferred(&square, &wide, &CompareMode::Reference);
        }

        #[test]
        fn nearly_square_proceeds_to_next_comparison() {
            let a = make_cover((600, 590), Format::Png);
            let b = make_cover((600, 595), Format::Jpeg);
            assert_eq!(
                compare(&a, &b, &CompareMode::Reference),
                cmp::Ordering::Greater
            );
        }

        #[test]
        fn squareness_ignores_orientation() {
            let portrait = make_cover((400, 800), Format::Jpeg);
            let landscape = make_cover((800, 400), Format::Jpeg);
            assert_eq!(
                compare(&portrait, &landscape, &CompareMode::Reference),
                cmp::Ordering::Equal
            );
        }

        #[test]
        fn search_mode_prefer_similar_to_reference() {
            let a = make_cover((600, 600), Format::Jpeg);
            let b = Cover {
                rank: 2,
                ..make_cover((600, 600), Format::Jpeg)
            };

            let mut hashes = HashMap::new();
            hashes.insert(a.key(), PerceptualHash::test_value1());
            hashes.insert(b.key(), PerceptualHash::test_value2());

            let reference = Some(SearchReference {
                reference: PerceptualHash::test_value1(),
                hashes,
            });
            let opts = make_search_opts(600);
            let mode = CompareMode::Search {
                search_opts: &opts,
                reference: &reference,
            };

            assert_preferred(&a, &b, &mode);
        }

        #[test]
        fn search_mode_no_reference_continues() {
            let a = make_cover((600, 600), Format::Png);
            let b = make_cover((600, 600), Format::Jpeg);
            let opts = make_search_opts(600);
            let mode = CompareMode::Search {
                search_opts: &opts,
                reference: &None,
            };
            assert_eq!(compare(&a, &b, &mode), cmp::Ordering::Greater);
        }

        #[test]
        fn search_mode_both_similar_to_reference_continues() {
            let a = make_cover((600, 600), Format::Png);
            let b = make_cover((600, 600), Format::Jpeg);

            let mut hashes = HashMap::new();
            hashes.insert(a.key(), PerceptualHash::test_value1());
            hashes.insert(b.key(), PerceptualHash::test_value1());

            let reference = Some(SearchReference {
                reference: PerceptualHash::test_value1(),
                hashes,
            });
            let opts = make_search_opts(600);
            let mode = CompareMode::Search {
                search_opts: &opts,
                reference: &reference,
            };
            assert_eq!(compare(&a, &b, &mode), cmp::Ordering::Greater);
        }

        #[test]
        fn search_mode_prefer_size_above_target() {
            let below = make_cover((400, 400), Format::Jpeg);
            let above = make_cover((700, 700), Format::Jpeg);
            let opts = make_search_opts(600);
            let mode = CompareMode::Search {
                search_opts: &opts,
                reference: &None,
            };
            assert_preferred(&above, &below, &mode);
        }

        #[test]
        fn search_mode_prefer_equal_to_target_over_below() {
            let below = make_cover((400, 400), Format::Jpeg);
            let equal = make_cover((600, 600), Format::Jpeg);
            let opts = make_search_opts(600);
            let mode = CompareMode::Search {
                search_opts: &opts,
                reference: &None,
            };
            assert_preferred(&equal, &below, &mode);
        }

        #[test]
        fn search_mode_both_above_target_continues() {
            let above1 = make_cover((700, 700), Format::Png);
            let above2 = make_cover((700, 700), Format::Jpeg);
            let opts = make_search_opts(600);
            let mode = CompareMode::Search {
                search_opts: &opts,
                reference: &None,
            };
            assert_eq!(compare(&above1, &above2, &mode), cmp::Ordering::Greater);
        }

        #[test]
        fn search_mode_both_below_prefer_closest() {
            let smaller = make_cover((300, 300), Format::Jpeg);
            let larger = make_cover((500, 500), Format::Jpeg);
            let opts = make_search_opts(600);
            let mode = CompareMode::Search {
                search_opts: &opts,
                reference: &None,
            };
            assert_preferred(&larger, &smaller, &mode);
        }

        #[test]
        fn prefer_better_relevance() {
            let high_relevance = make_cover((600, 600), Format::Jpeg);
            let low_relevance = Cover {
                relevance: Relevance::worst(),
                ..make_cover((600, 600), Format::Jpeg)
            };
            assert_preferred(&high_relevance, &low_relevance, &CompareMode::Reference);
        }

        #[test]
        fn prefer_better_rank() {
            let rank1 = make_cover((600, 600), Format::Jpeg);
            let rank2 = Cover {
                rank: 2,
                ..make_cover((600, 600), Format::Jpeg)
            };
            assert_preferred(&rank1, &rank2, &CompareMode::Reference);
        }

        #[test]
        fn prefer_known_size_metadata() {
            let known = make_cover((600, 600), Format::Jpeg);
            let uncertain = Cover {
                size_px: Metadata::uncertain((600, 600)),
                ..make_cover((600, 600), Format::Jpeg)
            };
            assert_preferred(&known, &uncertain, &CompareMode::Reference);
        }

        #[test]
        fn prefer_known_format_metadata() {
            let known = make_cover((600, 600), Format::Jpeg);
            let uncertain = Cover {
                format: Metadata::uncertain(Format::Jpeg),
                ..make_cover((600, 600), Format::Jpeg)
            };
            assert_preferred(&known, &uncertain, &CompareMode::Reference);
        }

        #[test]
        fn search_mode_prefer_closest_to_target_size() {
            let close = make_cover((650, 650), Format::Jpeg);
            let far = make_cover((900, 900), Format::Jpeg);
            let opts = make_search_opts(600);
            let mode = CompareMode::Search {
                search_opts: &opts,
                reference: &None,
            };
            assert_preferred(&close, &far, &mode);
        }

        #[test]
        fn prefer_png_over_jpeg() {
            let png = make_cover((600, 600), Format::Png);
            let jpeg = make_cover((600, 600), Format::Jpeg);
            assert_preferred(&png, &jpeg, &CompareMode::Reference);
        }

        #[test]
        fn final_tiebreaker_prefer_more_square() {
            let a = make_cover((600, 602), Format::Jpeg);
            let b = make_cover((600, 605), Format::Jpeg);
            assert_preferred(&a, &b, &CompareMode::Reference);
        }

        #[test]
        fn equal() {
            let a = make_cover((600, 600), Format::Jpeg);
            let b = make_cover((600, 600), Format::Jpeg);
            assert_eq!(
                compare(&a, &b, &CompareMode::Reference),
                cmp::Ordering::Equal
            );
        }

        #[test]
        fn both_sizes_known_or_both_uncertain_continues() {
            let both_known = make_cover((600, 600), Format::Png);
            let both_known2 = make_cover((600, 600), Format::Jpeg);
            assert_eq!(
                compare(&both_known, &both_known2, &CompareMode::Reference),
                cmp::Ordering::Greater
            );
        }

        #[test]
        fn both_formats_known_or_both_uncertain_continues() {
            let both_uncertain = Cover {
                format: Metadata::uncertain(Format::Png),
                ..make_cover((600, 600), Format::Png)
            };
            let both_uncertain2 = Cover {
                format: Metadata::uncertain(Format::Jpeg),
                ..make_cover((600, 600), Format::Jpeg)
            };
            assert_eq!(
                compare(&both_uncertain, &both_uncertain2, &CompareMode::Reference),
                cmp::Ordering::Greater
            );
        }

        #[test]
        fn search_mode_both_below_same_size_continues() {
            let a = make_cover((400, 400), Format::Png);
            let b = make_cover((400, 400), Format::Jpeg);
            let opts = make_search_opts(600);
            let mode = CompareMode::Search {
                search_opts: &opts,
                reference: &None,
            };
            assert_eq!(compare(&a, &b, &mode), cmp::Ordering::Greater);
        }

        #[test]
        fn reference_mode_skips_size_comparison() {
            let below = make_cover((400, 400), Format::Png);
            let above = make_cover((700, 700), Format::Jpeg);
            assert_eq!(
                compare(&below, &above, &CompareMode::Reference),
                cmp::Ordering::Greater
            );
        }

        #[test]
        fn search_mode_same_size_above_target_continues() {
            let a = make_cover((700, 700), Format::Png);
            let b = make_cover((700, 700), Format::Jpeg);
            let opts = make_search_opts(600);
            let mode = CompareMode::Search {
                search_opts: &opts,
                reference: &None,
            };
            assert_eq!(compare(&a, &b, &mode), cmp::Ordering::Greater);
        }

        #[test]
        fn transitive() {
            let sizes = [
                (300, 300),
                (330, 300),
                (600, 600),
                (630, 600),
                (660, 600),
                (690, 600),
                (720, 600),
                (900, 600),
                (1200, 600),
                (600, 720),
            ];
            let covers: Vec<Cover> = iproduct!(sizes, 1..=3, [Format::Jpeg, Format::Png])
                .map(|(size, rank, format)| Cover {
                    rank,
                    ..make_cover(size, format)
                })
                .collect();
            let opts = make_search_opts(600);
            for mode in [
                CompareMode::Reference,
                CompareMode::Search {
                    search_opts: &opts,
                    reference: &None,
                },
            ] {
                for (a, b, c) in iproduct!(&covers, &covers, &covers) {
                    if compare(a, b, &mode).is_le() && compare(b, c, &mode).is_le() {
                        assert!(compare(a, c, &mode).is_le());
                    }
                }
            }
        }
    }

    mod download {
        use std::{fs, io::Write as _, net::TcpListener, thread};

        use super::*;

        /// Serve `body` to a single HTTP request, and return its URL
        fn serve(body: Vec<u8>) -> reqwest::Url {
            let listener = TcpListener::bind("127.0.0.1:0").unwrap();
            let address = listener.local_addr().unwrap();
            thread::spawn(move || {
                let (mut stream, _) = listener.accept().unwrap();
                let mut reader = BufReader::new(&stream);
                while reader.skip_until(b'\n').unwrap() > 2 {}
                let len = body.len();
                write!(stream, "HTTP/1.1 200 OK\r\nContent-Length: {len}\r\n\r\n").unwrap();
                stream.write_all(&body).unwrap();
            });
            format!("http://{address}/cover.jpg").parse().unwrap()
        }

        /// Encode a single color image
        fn encode(width: u32, height: u32, format: image::ImageFormat) -> Vec<u8> {
            let mut buf = io::Cursor::new(Vec::new());
            image::RgbImage::from_pixel(width, height, image::Rgb([10, 20, 200]))
                .write_to(&mut buf, format)
                .unwrap();
            buf.into_inner()
        }

        /// Read the format and dimensions of an image file
        fn probe(path: &Path) -> (image::ImageFormat, (u32, u32)) {
            let reader = image::ImageReader::open(path)
                .unwrap()
                .with_guessed_format()
                .unwrap();
            let format = reader.format().unwrap();
            (format, reader.decode().unwrap().dimensions())
        }

        /// Download `cover` to `output` for target `size`, and return the path written
        async fn download(
            cover: Cover,
            output: &Path,
            preserve_format: bool,
            size: u32,
        ) -> anyhow::Result<PathBuf> {
            cover
                .download(
                    output,
                    &ImageProcessingArgs { preserve_format },
                    &make_search_opts(size),
                )
                .await
        }

        /// Download a JPEG cover to `filename`, and check it is copied unchanged to `cover.jpg`
        async fn assert_jpeg_copy(filename: &str, preserve_format: bool) {
            let body = encode(200, 200, image::ImageFormat::Jpeg);
            let cover = Cover {
                url: serve(body.clone()),
                ..make_cover((200, 200), Format::Jpeg)
            };
            let output_dir = tempfile::tempdir().unwrap();

            let written = download(
                cover,
                &output_dir.path().join(filename),
                preserve_format,
                200,
            )
            .await
            .unwrap();

            assert_eq!(written, output_dir.path().join("cover.jpg"));
            assert_eq!(fs::read(&written).unwrap(), body);
        }

        #[tokio::test]
        async fn reject_below_min_size() {
            let url = serve(encode(800, 300, image::ImageFormat::Jpeg));
            let expected = format!("Cover {url} is smaller than expected (800x300)");
            let cover = Cover {
                url,
                size_px: Metadata::uncertain((600, 600)),
                ..make_cover((600, 600), Format::Jpeg)
            };
            let output_dir = tempfile::tempdir().unwrap();

            let err = download(cover, &output_dir.path().join("cover.jpg"), false, 600)
                .await
                .unwrap_err();

            assert_eq!(err.to_string(), expected);
        }

        #[tokio::test]
        async fn copy() {
            assert_jpeg_copy("cover.jpg", false).await;
        }

        #[tokio::test]
        async fn convert_and_resize() {
            let cover = Cover {
                url: serve(encode(240, 180, image::ImageFormat::Jpeg)),
                size_px: Metadata::uncertain((200, 200)),
                format: Metadata::uncertain(Format::Png),
                ..make_cover((200, 200), Format::Png)
            };
            let output_dir = tempfile::tempdir().unwrap();
            let output = output_dir.path().join("cover.png");

            let written = download(cover, &output, false, 100).await.unwrap();

            assert_eq!(written, output);
            assert_eq!(probe(&written), (image::ImageFormat::Png, (100, 75)));
        }

        #[tokio::test]
        async fn preserve_format_crunches_png() {
            let body = encode(200, 200, image::ImageFormat::Png);
            let cover = Cover {
                url: serve(body.clone()),
                ..make_cover((200, 200), Format::Png)
            };
            let output_dir = tempfile::tempdir().unwrap();

            let written = download(cover, &output_dir.path().join("cover.jpg"), true, 200)
                .await
                .unwrap();

            assert_eq!(written, output_dir.path().join("cover.png"));
            assert!(fs::read(&written).unwrap().len() < body.len());
        }

        #[tokio::test]
        async fn preserve_format_copies_jpeg() {
            assert_jpeg_copy("cover.png", true).await;
        }

        #[tokio::test]
        async fn preserve_format_with_resize() {
            let cover = Cover {
                url: serve(encode(200, 200, image::ImageFormat::Png)),
                ..make_cover((200, 200), Format::Png)
            };
            let output_dir = tempfile::tempdir().unwrap();
            let output = output_dir.path().join("cover.jpg");

            let written = download(cover, &output, true, 100).await.unwrap();

            assert_eq!(written, output);
            assert_eq!(probe(&written), (image::ImageFormat::Jpeg, (100, 100)));
        }
    }
}
