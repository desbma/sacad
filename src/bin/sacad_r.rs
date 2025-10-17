//! Recursively search and download album covers for a music library

use std::{
    collections::HashSet,
    path::PathBuf,
    sync::{Arc, LazyLock, atomic::Ordering},
    time::Duration,
};

use anyhow::Context as _;
use async_channel::Receiver;
use clap::Parser as _;
use indicatif::{ProgressBar, ProgressStyle};
use sacad::{
    cl::{self, CoverOutput, ImageProcessingArgs, SearchOptions, SearchQuery},
    search_and_download, tags,
    walk::{AudioFileIterator, Stats},
};

/// Unit of work for worker tasks
#[derive(Debug)]
struct Work {
    /// Query to search for
    query: SearchQuery,
    /// Where to output the cover
    output: WorkOutput,
}

/// Where to output a cover
#[derive(Debug)]
enum WorkOutput {
    /// Embed into tags for given files
    Embed(Vec<PathBuf>),
    /// Write to file
    File(PathBuf),
}

/// Wrapper from the same type in `cl` module to add path conversion
struct CoverOutputPattern<S>(cl::CoverOutputPattern<S>);

impl<S: Clone> From<&cl::CoverOutputPattern<S>> for CoverOutputPattern<S> {
    fn from(value: &cl::CoverOutputPattern<S>) -> Self {
        Self(value.clone())
    }
}

impl<S: AsRef<str>> CoverOutputPattern<S> {
    #[cfg(test)]
    fn new(s: S) -> Self {
        Self(cl::CoverOutputPattern(s))
    }

    /// Replace `{artist}` and `{album}` placeholders in pattern
    fn to_path_buf(&self, artist: &str, album: &str) -> PathBuf {
        let safe_artist = Self::sanitize_for_path(artist);
        let safe_album = Self::sanitize_for_path(album);
        let path = self
            .0
            .0
            .as_ref()
            .replace("{artist}", &safe_artist)
            .replace("{album}", &safe_album);
        PathBuf::from(path)
    }

    fn sanitize_for_path(s: &str) -> String {
        static VALID_ASCII_PUNCTUATION: LazyLock<HashSet<char>> =
            LazyLock::new(|| "-_.()!#$%&'@^{}~".chars().collect());
        s.chars()
            .filter_map(|c| match c {
                '/' | '\\' => Some('-'),
                '|' | '*' => Some('x'),
                c if c.is_ascii_alphanumeric()
                    || VALID_ASCII_PUNCTUATION.contains(&c)
                    || (c == ' ') =>
                {
                    Some(c)
                }
                _ => None,
            })
            .collect::<String>()
            .trim_matches([' ', '.'])
            .chars()
            .collect()
    }
}

/// The workers are IO bound and limited by source rate limits, so no need for more than that
const WORKER_COUNT: usize = 8;

/// Worker entry point
async fn worker(
    work_rx: Receiver<Work>,
    search_opts: Arc<SearchOptions>,
    image_proc: Arc<ImageProcessingArgs>,
    stats: Arc<Stats>,
    progress_bar: ProgressBar,
) -> anyhow::Result<()> {
    while let Ok(work) = work_rx.recv().await {
        if let Err(err) = handle_work(work, &search_opts, &image_proc, &stats, &progress_bar).await
        {
            stats.errors.fetch_add(1, Ordering::Relaxed);
            log::warn!("{err}");
        }
    }
    Ok(())
}

/// Update the progress bar message from current stats
fn update_progress_bar(stats: &Stats, progress_bar: &ProgressBar) {
    let done = stats.done.load(Ordering::Relaxed);
    let no_result = stats.no_result_found.load(Ordering::Relaxed);
    let errors = stats.errors.load(Ordering::Relaxed);
    let missing = stats.missing_covers.load(Ordering::Relaxed);
    let audio_files = stats.audio_files.load(Ordering::Relaxed);
    let audio_dirs = stats.audio_dirs.load(Ordering::Relaxed);

    progress_bar.set_length(missing.try_into().unwrap_or(u64::MAX));
    progress_bar.set_position((done + no_result + errors).try_into().unwrap_or(u64::MAX));
    progress_bar.set_message(format!(
        "dirs:{audio_dirs} files:{audio_files} missing:{missing} done:{done} not_found:{no_result} errs:{errors}"
    ));
}

/// Worker function to handle a single work item
async fn handle_work(
    work: Work,
    search_opts: &Arc<SearchOptions>,
    image_proc: &Arc<ImageProcessingArgs>,
    stats: &Arc<Stats>,
    progress_bar: &ProgressBar,
) -> anyhow::Result<()> {
    let (output, _tmp_file) = match &work.output {
        WorkOutput::Embed(_) => {
            let tmp_file = tempfile::NamedTempFile::new()?;
            (tmp_file.path().to_owned(), Some(tmp_file))
        }
        WorkOutput::File(filepath) => (filepath.to_owned(), None),
    };
    match search_and_download(
        &output,
        Arc::new(work.query),
        Arc::clone(search_opts),
        image_proc,
    )
    .await?
    {
        sacad::SearchStatus::Found => {
            if let WorkOutput::Embed(audio_files) = work.output {
                tags::embed_cover(&output, audio_files)?;
            }
            stats.done.fetch_add(1, Ordering::Relaxed);
        }
        sacad::SearchStatus::NotFound => {
            stats.no_result_found.fetch_add(1, Ordering::Relaxed);
        }
    }
    update_progress_bar(stats, progress_bar);
    Ok(())
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Parse CL args
    let cl_args = cl::SacadRecursiveArgs::parse();

    // Init logger
    simple_logger::init_with_level(cl_args.verbosity).context("Failed to setup logger")?;

    // Create progress bar
    let stats = Arc::default();
    let progress_bar = ProgressBar::new(0);
    progress_bar.set_style(
        ProgressStyle::default_bar()
            .template("{spinner} [{elapsed_precise}/{duration_precise}] [{bar}] {pos}/{len} {percent}% {wide_msg}")?,
    );
    progress_bar.enable_steady_tick(Duration::from_millis(300));
    update_progress_bar(&stats, &progress_bar);

    // Start workers
    let search_opts = Arc::new(cl_args.search_opts);
    let image_proc = Arc::new(cl_args.image_proc);
    let (work_tx, work_rx) = async_channel::bounded::<Work>(1024);
    let mut workers = Vec::with_capacity(WORKER_COUNT);
    for _ in 0..WORKER_COUNT {
        let worker_work_rx = work_rx.clone();
        let worker_search_opts = Arc::clone(&search_opts);
        let worker_image_proc = Arc::clone(&image_proc);
        let worker_stats = Arc::clone(&stats);
        let worker_progress_bar = progress_bar.clone();
        let worker = tokio::spawn(async {
            if let Err(err) = worker(
                worker_work_rx,
                worker_search_opts,
                worker_image_proc,
                worker_stats,
                worker_progress_bar,
            )
            .await
            {
                log::error!("Worker errored: {err}");
            }
        });
        workers.push(worker);
    }

    // Walk library
    for audio_files in AudioFileIterator::new(&cl_args.lib_root_dir, Arc::clone(&stats)) {
        update_progress_bar(&stats, &progress_bar);

        // Read tags
        let Some(tags) =
            tags::read_metadata(&audio_files, matches!(cl_args.output, CoverOutput::Embed))
        else {
            log::warn!("Unable to extract metadata from files {audio_files:?}");
            stats.errors.fetch_add(1, Ordering::Relaxed);
            continue;
        };

        // Compute output
        let output = match &cl_args.output {
            CoverOutput::Embed => WorkOutput::Embed(audio_files),
            CoverOutput::Pattern(pattern) => {
                let pattern: CoverOutputPattern<_> = pattern.into();
                WorkOutput::File(pattern.to_path_buf(&tags.artist, &tags.album))
            }
        };

        // Check if cover is missing
        let has_cover = match &output {
            #[expect(clippy::unwrap_used)]
            WorkOutput::Embed(_) => tags.has_embedded_cover.unwrap(),
            WorkOutput::File(path) => path.exists(),
        };
        if has_cover && !cl_args.ignore_existing {
            continue;
        }
        if !has_cover {
            stats.missing_covers.fetch_add(1, Ordering::Relaxed);
        }

        // Send work
        let query = SearchQuery {
            artist: tags.artist,
            album: tags.album,
        };
        work_tx.send_blocking(Work { query, output })?;
    }

    drop(work_tx);
    for worker in workers {
        let _ = worker.await;
    }

    progress_bar.finish();

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn output_pattern_basic_replacement() {
        let pattern = CoverOutputPattern::new("covers/{artist}/{album}.jpg");
        let result = pattern.to_path_buf("The Beatles", "Abbey Road");
        assert_eq!(result, PathBuf::from("covers/The Beatles/Abbey Road.jpg"));
    }

    #[test]
    fn output_pattern_single_placeholder() {
        let pattern = CoverOutputPattern::new("{album}_cover.jpg");
        let result = pattern.to_path_buf("Artist Name", "Album Name");
        assert_eq!(result, PathBuf::from("Album Name_cover.jpg"));
    }

    #[test]
    fn output_pattern_multiple_occurrences() {
        let pattern = CoverOutputPattern::new("{artist}_{artist}_{album}.jpg");
        let result = pattern.to_path_buf("Pink Floyd", "Dark Side");
        assert_eq!(result, PathBuf::from("Pink Floyd_Pink Floyd_Dark Side.jpg"));
    }

    #[test]
    fn output_pattern_no_placeholders() {
        let pattern = CoverOutputPattern::new("cover.jpg");
        let result = pattern.to_path_buf("Artist", "Album");
        assert_eq!(result, PathBuf::from("cover.jpg"));
    }

    #[test]
    fn output_pattern_with_special_chars() {
        let pattern = CoverOutputPattern::new("{artist} - {album}/cover.jpg");
        let result = pattern.to_path_buf("Metallica", "Master of Puppets");
        assert_eq!(
            result,
            PathBuf::from("Metallica - Master of Puppets/cover.jpg")
        );
    }

    #[test]
    fn output_pattern_sanitizes_forward_slashes() {
        let pattern = CoverOutputPattern::new("covers/{artist}/{album}.jpg");
        let result = pattern.to_path_buf("AC/DC", "Back/in Black");
        // / becomes -
        assert_eq!(result, PathBuf::from("covers/AC-DC/Back-in Black.jpg"));
    }

    #[test]
    fn output_pattern_sanitizes_backslashes() {
        let pattern = CoverOutputPattern::new("{artist}_{album}.jpg");
        let result = pattern.to_path_buf("Foo\\Bar", "Album\\Name");
        // \ becomes -
        assert_eq!(result, PathBuf::from("Foo-Bar_Album-Name.jpg"));
    }

    #[test]
    fn output_pattern_sanitizes_pipes_and_asterisks() {
        let pattern = CoverOutputPattern::new("{artist}_{album}.jpg");
        let result = pattern.to_path_buf("Artist|Name", "Album*Name");
        // | and * become x
        assert_eq!(result, PathBuf::from("ArtistxName_AlbumxName.jpg"));
    }

    #[test]
    fn output_pattern_removes_trailing_dots() {
        let pattern = CoverOutputPattern::new("{artist}_{album}.jpg");
        let result = pattern.to_path_buf("Artist.", "Album...");
        assert_eq!(result, PathBuf::from("Artist_Album.jpg"));
    }

    #[test]
    fn output_pattern_trims_whitespace() {
        let pattern = CoverOutputPattern::new("{artist}_{album}.jpg");
        let result = pattern.to_path_buf("  Artist  ", "  Album  ");
        assert_eq!(result, PathBuf::from("Artist_Album.jpg"));
    }
}
