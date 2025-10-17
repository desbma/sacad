//! HTTP cache

#![expect(clippy::result_large_err)]

use std::path::Path;

/// On-disk key-value cache
pub(super) struct Cache {
    /// Inner database
    db: redb::Database,
}

/// Error the cache can return
#[derive(thiserror::Error, Debug)]
#[expect(clippy::missing_docs_in_private_items, clippy::large_enum_variant)]
pub(crate) enum CacheError {
    #[error("Decoding error: {0}")]
    Bitcode(#[from] bitcode::Error),
    #[error("Database commit error: {0}")]
    Commit(#[from] redb::CommitError),
    #[error("Database error: {0}")]
    Database(#[from] redb::DatabaseError),
    #[error("Decompression error: {0}")]
    LZ4(#[from] lz4_flex::block::DecompressError),
    #[error("Database storage error: {0}")]
    Storage(#[from] redb::StorageError),
    #[error("Database table error: {0}")]
    Table(#[from] redb::TableError),
    #[error("Database transaction error: {0}")]
    Transaction(#[from] redb::TransactionError),
}

/// redb table for cache
const REDB_TABLE: redb::TableDefinition<&str, Vec<u8>> = redb::TableDefinition::new("cache_v1");

impl Cache {
    /// Create a new cache instance
    pub(crate) fn new<P>(path: P) -> Result<Self, CacheError>
    where
        P: AsRef<Path>,
    {
        // TODO periodic scan all to evict old entries + compact
        Ok(Self {
            db: redb::Database::create(path)?,
        })
    }

    /// Get a single value from cache
    pub(crate) fn get<K, V>(&self, key: K) -> Result<Option<V>, CacheError>
    where
        K: AsRef<str>,
        V: bitcode::DecodeOwned,
    {
        let db_read = self.db.begin_read()?;
        let table = match db_read.open_table(REDB_TABLE) {
            Ok(table) => table,
            Err(redb::TableError::TableDoesNotExist(_)) => return Ok(None),
            Err(err) => return Err(err.into()),
        };
        if let Some(raw_value) = table.get(key.as_ref())? {
            let encoded = lz4_flex::decompress_size_prepended(&raw_value.value())?;
            let value: V = bitcode::decode(&encoded)?;
            Ok(Some(value))
        } else {
            Ok(None)
        }
    }

    /// Set single value in cache
    pub(crate) fn set<K, V>(&mut self, k: K, v: &V) -> Result<(), CacheError>
    where
        K: AsRef<str>,
        V: bitcode::Encode,
    {
        self.set_multi(&[(k, v)])
    }

    /// Set multiple values in cache in a single transaction
    pub(crate) fn set_multi<K, V>(&mut self, kvs: &[(K, &V)]) -> Result<(), CacheError>
    where
        K: AsRef<str>,
        V: bitcode::Encode,
    {
        let db_write = self.db.begin_write()?;
        {
            let mut table = db_write.open_table(REDB_TABLE)?;
            #[expect(clippy::cast_precision_loss)]
            for (k, v) in kvs {
                let encoded = bitcode::encode(*v);
                let compressed = lz4_flex::compress_prepend_size(&encoded);
                log::debug!(
                    "Data for cache key {} compression ratio: {:.2}%",
                    k.as_ref(),
                    compressed.len() as f64 * 100.0 / encoded.len() as f64
                );
                table.insert(k.as_ref(), compressed)?;
            }
        }
        db_write.commit()?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(bitcode::Encode, bitcode::Decode)]
    struct Data(String);

    #[test]
    fn set_get() {
        let temp_file = tempfile::NamedTempFile::new().unwrap();
        let mut cache = Cache::new(temp_file.path()).unwrap();
        cache
            .set_multi(&[
                ("key1", &Data("value1".to_owned())),
                ("key2", &Data("value2".to_owned())),
            ])
            .unwrap();
        assert_eq!(cache.get::<_, Data>("key1").unwrap().unwrap().0, "value1");
        assert_eq!(cache.get::<_, Data>("key2").unwrap().unwrap().0, "value2");
    }

    #[test]
    fn set_get_new_cache() {
        let temp_file = tempfile::NamedTempFile::new().unwrap();
        {
            let mut cache = Cache::new(temp_file.path()).unwrap();
            cache
                .set_multi(&[
                    ("key1", &Data("value1".to_owned())),
                    ("key2", &Data("value2".to_owned())),
                ])
                .unwrap();
        }
        let cache = Cache::new(temp_file.path()).unwrap();
        assert_eq!(cache.get::<_, Data>("key1").unwrap().unwrap().0, "value1");
        assert_eq!(cache.get::<_, Data>("key2").unwrap().unwrap().0, "value2");
    }
}
