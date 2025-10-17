//! Code to walk library tree

use std::{
    collections::HashSet,
    fs,
    path::{Path, PathBuf},
    sync::{
        Arc, LazyLock,
        atomic::{AtomicUsize, Ordering},
    },
};

/// Real time stats of global processing
#[derive(Default)]
pub struct Stats {
    /// Count of files identified as audio
    pub audio_files: AtomicUsize,
    /// Count of directories with at least an audio file
    pub audio_dirs: AtomicUsize,
    /// Count of covers needing search & download
    pub missing_covers: AtomicUsize,
    /// Count of covers successfully downloaded
    pub done: AtomicUsize,
    /// Count of searches that yielded no result
    pub no_result_found: AtomicUsize,
    /// Total error count
    pub errors: AtomicUsize,
}

/// Iterator that yields paths of audio files from the same level
pub struct AudioFileIterator {
    dirs: Vec<PathBuf>,
    stats: Arc<Stats>,
}

impl AudioFileIterator {
    /// Create an iterator that yields paths of audio files from the same level
    pub fn new(dir: &Path, stats: Arc<Stats>) -> Self {
        Self {
            dirs: vec![dir.to_owned()],
            stats,
        }
    }

    fn is_audio_file(path: &Path) -> bool {
        static AUDIO_EXTENSIONS: LazyLock<HashSet<&str>> = LazyLock::new(|| {
            [
                "aac", "ape", "flac", "m4a", "mp3", "mp4", "mpc", "ogg", "oga", "opus", "tta", "wv",
            ]
            .into_iter()
            .collect()
        });
        path.extension()
            .and_then(|ext| ext.to_str())
            .is_some_and(|ext| AUDIO_EXTENSIONS.contains(ext.to_lowercase().as_str()))
    }
}

impl Iterator for AudioFileIterator {
    type Item = Vec<PathBuf>;

    fn next(&mut self) -> Option<Self::Item> {
        while let Some(dir) = self.dirs.pop() {
            let mut audio_files = Vec::new();
            let dir_it = match fs::read_dir(&dir) {
                Ok(dir_it) => dir_it,
                Err(err) => {
                    self.stats.errors.fetch_add(1, Ordering::Relaxed);
                    log::warn!("Failed to read dir {dir:?}: {err}");
                    continue;
                }
            };
            for entry_res in dir_it {
                let entry = match entry_res {
                    Ok(entry) => entry,
                    Err(err) => {
                        self.stats.errors.fetch_add(1, Ordering::Relaxed);
                        log::warn!("Failed to read dir {dir:?} entry: {err}");
                        continue;
                    }
                };
                let ftype = match entry.file_type() {
                    Ok(ftype) => ftype,
                    Err(err) => {
                        self.stats.errors.fetch_add(1, Ordering::Relaxed);
                        log::warn!("Failed to read dir {dir:?} entry: {err}");
                        continue;
                    }
                };
                let path = entry.path();
                if ftype.is_dir() {
                    self.dirs.push(path);
                } else if ftype.is_file() && Self::is_audio_file(&path) {
                    audio_files.push(path);
                }
            }
            if !audio_files.is_empty() {
                self.stats.audio_dirs.fetch_add(1, Ordering::Relaxed);
                self.stats
                    .audio_files
                    .fetch_add(audio_files.len(), Ordering::Relaxed);
                return Some(audio_files);
            }
        }
        None
    }
}
