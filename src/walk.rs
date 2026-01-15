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
    pub fn new<P>(dir: P, stats: Arc<Stats>) -> Self
    where
        P: AsRef<Path>,
    {
        Self {
            dirs: vec![dir.as_ref().to_owned()],
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

#[cfg(test)]
mod tests {
    use std::sync::atomic::Ordering;

    use super::*;

    fn create_file<P>(dir: P, ext: &str)
    where
        P: AsRef<Path>,
    {
        tempfile::Builder::new()
            .suffix(&format!(".{ext}"))
            .tempfile_in(dir)
            .unwrap()
            .keep()
            .unwrap();
    }

    #[test]
    fn empty_directory() {
        let tmp_dir = tempfile::tempdir().unwrap();
        let stats = Arc::new(Stats::default());

        let items: Vec<_> = AudioFileIterator::new(&tmp_dir, Arc::clone(&stats)).collect();

        assert!(items.is_empty());
        assert_eq!(stats.audio_files.load(Ordering::Relaxed), 0);
        assert_eq!(stats.audio_dirs.load(Ordering::Relaxed), 0);
        assert_eq!(stats.errors.load(Ordering::Relaxed), 0);
    }

    #[test]
    fn single_audio_file() {
        let tmp_dir = tempfile::tempdir().unwrap();
        create_file(&tmp_dir, "mp3");
        let stats = Arc::new(Stats::default());

        let items: Vec<_> = AudioFileIterator::new(&tmp_dir, Arc::clone(&stats)).collect();

        assert_eq!(items.len(), 1);
        assert_eq!(items[0].len(), 1);
        assert_eq!(stats.audio_files.load(Ordering::Relaxed), 1);
        assert_eq!(stats.audio_dirs.load(Ordering::Relaxed), 1);
    }

    #[test]
    fn multiple_audio_files_same_dir() {
        let tmp_dir = tempfile::tempdir().unwrap();
        create_file(&tmp_dir, "flac");
        create_file(&tmp_dir, "ogg");
        create_file(&tmp_dir, "opus");
        let stats = Arc::new(Stats::default());

        let items: Vec<_> = AudioFileIterator::new(&tmp_dir, Arc::clone(&stats)).collect();

        assert_eq!(items.len(), 1);
        assert_eq!(items[0].len(), 3);
        assert_eq!(stats.audio_files.load(Ordering::Relaxed), 3);
        assert_eq!(stats.audio_dirs.load(Ordering::Relaxed), 1);
    }

    #[test]
    fn ignores_non_audio_files() {
        let tmp_dir = tempfile::tempdir().unwrap();
        create_file(&tmp_dir, "mp3");
        create_file(&tmp_dir, "jpg");
        create_file(&tmp_dir, "txt");
        let stats = Arc::new(Stats::default());

        let items: Vec<_> = AudioFileIterator::new(&tmp_dir, Arc::clone(&stats)).collect();

        assert_eq!(items.len(), 1);
        assert_eq!(items[0].len(), 1);
        assert_eq!(stats.audio_files.load(Ordering::Relaxed), 1);
    }

    #[test]
    fn nested_directories() {
        let tmp_dir = tempfile::tempdir().unwrap();
        let artist = tmp_dir.path().join("Artist");
        let album1 = artist.join("Album1");
        let album2 = artist.join("Album2");
        fs::create_dir_all(&album1).unwrap();
        fs::create_dir_all(&album2).unwrap();

        create_file(&album1, "mp3");
        create_file(&album1, "mp3");
        create_file(&album2, "flac");
        let stats = Arc::new(Stats::default());

        let items: Vec<_> = AudioFileIterator::new(&tmp_dir, Arc::clone(&stats)).collect();

        assert_eq!(items.len(), 2);
        assert_eq!(stats.audio_files.load(Ordering::Relaxed), 3);
        assert_eq!(stats.audio_dirs.load(Ordering::Relaxed), 2);
    }

    #[test]
    fn skips_empty_subdirs() {
        let tmp = tempfile::tempdir().unwrap();
        fs::create_dir(tmp.path().join("empty")).unwrap();
        let with_audio = tmp.path().join("music");
        fs::create_dir(&with_audio).unwrap();
        create_file(&with_audio, "m4a");
        let stats = Arc::new(Stats::default());

        let items: Vec<_> = AudioFileIterator::new(tmp.path(), Arc::clone(&stats)).collect();

        assert_eq!(items.len(), 1);
        assert_eq!(stats.audio_dirs.load(Ordering::Relaxed), 1);
    }

    #[test]
    fn audio_extension_case_insensitive() {
        let tmp = tempfile::tempdir().unwrap();
        create_file(&tmp, "MP3");
        create_file(&tmp, "FlAc");
        let stats = Arc::new(Stats::default());

        let items: Vec<_> = AudioFileIterator::new(tmp.path(), Arc::clone(&stats)).collect();

        assert_eq!(items[0].len(), 2);
        assert_eq!(stats.audio_files.load(Ordering::Relaxed), 2);
    }

    #[test]
    fn all_supported_extensions() {
        let tmp = tempfile::tempdir().unwrap();
        let extensions = [
            "aac", "ape", "flac", "m4a", "mp3", "mp4", "mpc", "ogg", "oga", "opus", "tta", "wv",
        ];
        for ext in extensions {
            create_file(&tmp, ext);
        }
        let stats = Arc::new(Stats::default());

        let items: Vec<_> = AudioFileIterator::new(tmp.path(), Arc::clone(&stats)).collect();

        assert_eq!(items[0].len(), 12);
        assert_eq!(stats.audio_files.load(Ordering::Relaxed), 12);
    }

    #[test]
    fn nonexistent_directory_counts_error() {
        let tmp = tempfile::tempdir().unwrap();
        let nonexistent = tmp.path().join("does_not_exist");
        let stats = Arc::new(Stats::default());

        let items: Vec<_> = AudioFileIterator::new(&nonexistent, Arc::clone(&stats)).collect();

        assert!(items.is_empty());
        assert_eq!(stats.errors.load(Ordering::Relaxed), 1);
    }
}
