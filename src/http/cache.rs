//! HTTP cache

use std::{
    collections::HashMap,
    fmt, fs,
    marker::PhantomData,
    path::Path,
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use anyhow::Context as _;
use const_format::formatcp;
use parking_lot::Mutex;
use redb::ReadableDatabase as _;
use tokio::sync::Mutex as AsyncMutex;

/// Cache entry, as set in database
type CacheEntryInner = (u64, Vec<u8>);

/// Compression algorithm
pub(crate) trait Compressor {
    fn compress(data: &[u8]) -> Vec<u8>;
    fn decompress(data: &[u8]) -> Result<Vec<u8>, CacheError>;
}

/// LZ4
pub(crate) struct Lz4Compressor;

impl Compressor for Lz4Compressor {
    fn compress(data: &[u8]) -> Vec<u8> {
        lz4_flex::compress_prepend_size(data)
    }

    fn decompress(data: &[u8]) -> Result<Vec<u8>, CacheError> {
        Ok(lz4_flex::decompress_size_prepended(data)?)
    }
}

/// Compressor that does nothing
pub(crate) struct NullCompressor;

impl Compressor for NullCompressor {
    fn compress(data: &[u8]) -> Vec<u8> {
        data.to_vec()
    }

    fn decompress(data: &[u8]) -> Result<Vec<u8>, CacheError> {
        Ok(data.to_vec())
    }
}

/// High level cache entry
struct CacheEntry<C> {
    inner: CacheEntryInner,
    compression: PhantomData<C>,
}

impl<C: Compressor> CacheEntry<C> {
    /// Create a new cache entry from uncompressed data
    fn from_uncompressed(data: &[u8]) -> Self {
        Self {
            inner: (Self::now(), C::compress(data)),
            compression: PhantomData::<C>,
        }
    }

    /// Access uncompressed data from cache entry
    fn data(inner: &CacheEntryInner) -> Result<Vec<u8>, CacheError> {
        C::decompress(&inner.1)
    }

    /// Get current time in seconds since epoch
    /// Warning: this can move backwards if system time changes
    fn now() -> u64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or(Duration::ZERO)
            .as_secs()
    }
}

/// On-disk key-value cache
#[derive(Debug)]
pub(super) struct Cache<C> {
    /// Inner database
    db: redb::Database,
    /// Compression
    compression: PhantomData<C>,
    /// Locks for pending updates, for use with `get_or_set`
    busy: Mutex<HashMap<String, Arc<AsyncMutex<()>>>>,
}

/// Error the cache can return
#[derive(thiserror::Error, Debug)]
pub(crate) enum CacheError {
    #[error("Database commit error: {0}")]
    Commit(#[from] redb::CommitError),
    #[error("Database compaction error: {0}")]
    Compaction(#[from] redb::CompactionError),
    #[error("Database error: {0}")]
    Database(#[from] redb::DatabaseError),
    #[error("Cache filepath error: {0}")]
    File(anyhow::Error),
    #[error("Decompression error: {0}")]
    LZ4(#[from] lz4_flex::block::DecompressError),
    #[error("Database storage error: {0}")]
    Storage(#[from] redb::StorageError),
    #[error("Database table error: {0}")]
    Table(#[from] redb::TableError),
    #[error("Database transaction error: {0}")]
    Transaction(#[from] redb::TransactionError),
    #[error("Cache update error: {0}")]
    Update(anyhow::Error),
}

/// External (file) database format version
const EXTERNAL_FORMAT_VERSION: usize = 1;
/// Internal (scheme/content) database format version
const INTERNAL_FORMAT_VERSION: usize = 1;

/// redb table for cache
const REDB_TABLE: redb::TableDefinition<&str, CacheEntryInner> =
    redb::TableDefinition::new(formatcp!("cache_v{}", INTERNAL_FORMAT_VERSION));

impl<C: Compressor> Cache<C> {
    /// Create a new cache instance in XDG cache directory
    pub(crate) fn new<N>(name: N, max_age: Duration) -> Result<Self, CacheError>
    where
        N: AsRef<str>,
    {
        let dirs =
            directories::ProjectDirs::from("", "", env!("CARGO_PKG_NAME")).ok_or_else(|| {
                CacheError::File(anyhow::anyhow!("Unable to compute cache directory"))
            })?;
        let cache_dir = dirs.cache_dir();
        fs::create_dir_all(cache_dir)
            .with_context(|| format!("Failed to create dir {cache_dir:?}"))
            .map_err(CacheError::File)?;
        let cache_path = cache_dir.join(format!(
            "{}_{:02x}.db",
            name.as_ref(),
            EXTERNAL_FORMAT_VERSION
        ));

        Self::with_path(cache_path, max_age)
    }

    /// Create a new cache instance at a given path
    fn with_path<P>(path: P, max_age: Duration) -> Result<Self, CacheError>
    where
        P: AsRef<Path> + fmt::Debug,
    {
        let mut cache = Self {
            db: redb::Database::create(path.as_ref())?,
            compression: PhantomData::<C>,
            busy: Mutex::default(),
        };
        let removed = cache.maintenance(max_age)?;
        log::debug!("Removed {removed} cache entries from {path:?}");
        Ok(cache)
    }

    /// Evict old cache entries and compact database
    fn maintenance(&mut self, max_age: Duration) -> Result<usize, CacheError> {
        let mut removed = 0;
        let now = SystemTime::now();
        let db_write = self.db.begin_write()?;
        {
            let mut table = db_write.open_table(REDB_TABLE)?;
            table.retain(|_k, entry| {
                let Some(entry_created) = UNIX_EPOCH.checked_add(Duration::from_secs(entry.0))
                else {
                    // Entry has invalid time, nuke it
                    removed += 1;
                    return false;
                };
                let keep = now
                    .duration_since(entry_created)
                    .is_ok_and(|d| d <= max_age);
                if !keep {
                    removed += 1;
                }
                keep
            })?;
        }
        db_write.commit()?;
        if removed > 0 {
            self.db.compact()?;
        }
        Ok(removed)
    }

    /// Get a single value from cache
    pub(crate) fn get<K>(&self, key: K) -> Result<Option<Vec<u8>>, CacheError>
    where
        K: AsRef<str>,
    {
        let db_read = self.db.begin_read()?;
        let table = match db_read.open_table(REDB_TABLE) {
            Ok(table) => table,
            Err(redb::TableError::TableDoesNotExist(_)) => return Ok(None),
            Err(err) => return Err(err.into()),
        };
        if let Some(raw_value) = table.get(key.as_ref())? {
            let value = CacheEntry::<C>::data(&raw_value.value())?;
            Ok(Some(value))
        } else {
            Ok(None)
        }
    }

    /// Get cache entry, or set it atomically (prevents thundering herd)
    pub(crate) async fn get_or_set<K, S>(&self, key: K, setter: S) -> Result<Vec<u8>, CacheError>
    where
        K: AsRef<str>,
        S: Future<Output = anyhow::Result<Vec<u8>>>,
    {
        let key: &str = key.as_ref();
        let entry_mutex = Arc::clone(self.busy.lock().entry(key.to_owned()).or_default());
        let _entry_lock = entry_mutex.lock().await;

        if let Some(value) = self.get(key)? {
            Ok(value)
        } else {
            let value = setter.await.map_err(CacheError::Update)?;
            self.set(key, &value)?;
            Ok(value)
        }

        // Note we don't remove locks from hashmap beacuse that would be racy,
        // and that won't use much memory anyway
    }

    /// Set single value in cache
    pub(crate) fn set<K>(&self, k: K, v: &[u8]) -> Result<(), CacheError>
    where
        K: AsRef<str>,
    {
        self.set_multi(&[(k, v)])
    }

    /// Set multiple values in cache in a single transaction
    pub(crate) fn set_multi<K>(&self, kvs: &[(K, &[u8])]) -> Result<(), CacheError>
    where
        K: AsRef<str>,
    {
        let db_write = self.db.begin_write()?;
        {
            let mut table = db_write.open_table(REDB_TABLE)?;
            #[expect(clippy::cast_precision_loss, clippy::cast_possible_truncation)]
            for (k, v) in kvs {
                let entry = CacheEntry::<C>::from_uncompressed(v);
                log::debug!(
                    "Data for cache key {} size {} (compression ratio: {:.2}%)",
                    k.as_ref(),
                    human_bytes::human_bytes(entry.inner.1.len() as u32),
                    entry.inner.1.len() as f64 * 100.0 / v.len() as f64
                );
                table.insert(k.as_ref(), entry.inner)?;
            }
        }
        db_write.commit()?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use std::sync::atomic::{AtomicUsize, Ordering};

    #[test]
    fn set_get() {
        let temp_file = tempfile::NamedTempFile::new().unwrap();
        let cache =
            Cache::<Lz4Compressor>::with_path(temp_file.path(), Duration::from_hours(1)).unwrap();
        cache
            .set_multi(&[("key1", "value1".as_bytes()), ("key2", "value2".as_bytes())])
            .unwrap();
        assert_eq!(cache.get("key1").unwrap().unwrap(), "value1".as_bytes());
        assert_eq!(cache.get("key2").unwrap().unwrap(), "value2".as_bytes());
    }

    #[test]
    fn set_get_new_cache() {
        let temp_file = tempfile::NamedTempFile::new().unwrap();
        {
            let cache =
                Cache::<Lz4Compressor>::with_path(temp_file.path(), Duration::from_hours(1))
                    .unwrap();
            cache
                .set_multi(&[("key1", "value1".as_bytes()), ("key2", "value2".as_bytes())])
                .unwrap();
        }
        let cache =
            Cache::<Lz4Compressor>::with_path(temp_file.path(), Duration::from_hours(1)).unwrap();
        assert_eq!(cache.get("key1").unwrap().unwrap(), "value1".as_bytes());
        assert_eq!(cache.get("key2").unwrap().unwrap(), "value2".as_bytes());
    }

    #[tokio::test]
    async fn get_or_set_basic() {
        let temp_file = tempfile::NamedTempFile::new().unwrap();
        let cache =
            Cache::<Lz4Compressor>::with_path(temp_file.path(), Duration::from_hours(1)).unwrap();

        let result1 = cache
            .get_or_set("key1", async { Ok(b"value1".to_vec()) })
            .await
            .unwrap();
        assert_eq!(result1, b"value1");

        let result2 = cache
            .get_or_set("key1", async { Ok(b"value2".to_vec()) })
            .await
            .unwrap();
        assert_eq!(result2, b"value1");
    }

    #[tokio::test]
    async fn get_or_set_no_race_condition() {
        let temp_file = tempfile::NamedTempFile::new().unwrap();
        let cache = Arc::new(
            Cache::<Lz4Compressor>::with_path(temp_file.path(), Duration::from_hours(1)).unwrap(),
        );
        let call_count = Arc::new(AtomicUsize::new(0));

        let mut handles = Vec::new();
        for _ in 0..10 {
            let cache = Arc::clone(&cache);
            let call_count = Arc::clone(&call_count);
            handles.push(tokio::spawn(async move {
                cache
                    .get_or_set("key1", async {
                        call_count.fetch_add(1, Ordering::SeqCst);
                        tokio::time::sleep(Duration::from_millis(500)).await;
                        Ok(b"value1".to_vec())
                    })
                    .await
                    .unwrap()
            }));
        }

        let results: Vec<_> = futures::future::join_all(handles)
            .await
            .into_iter()
            .map(Result::unwrap)
            .collect();

        assert!(results.iter().all(|r| r == b"value1"));
        assert_eq!(call_count.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn get_or_set_different_keys_parallel() {
        let temp_file = tempfile::NamedTempFile::new().unwrap();
        let cache = Arc::new(
            Cache::<Lz4Compressor>::with_path(temp_file.path(), Duration::from_hours(1)).unwrap(),
        );
        let call_count = Arc::new(AtomicUsize::new(0));

        let mut handles = Vec::new();
        for i in 0..5 {
            let cache = Arc::clone(&cache);
            let call_count = Arc::clone(&call_count);
            let key = format!("key{i}");
            let value = format!("value{i}").into_bytes();
            handles.push(tokio::spawn(async move {
                cache
                    .get_or_set(key, async {
                        call_count.fetch_add(1, Ordering::SeqCst);
                        Ok(value)
                    })
                    .await
                    .unwrap()
            }));
        }

        futures::future::join_all(handles).await;

        assert_eq!(call_count.load(Ordering::SeqCst), 5);
    }
}
