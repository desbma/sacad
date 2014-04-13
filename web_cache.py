""" Persistent cache storage for web ressources, with different cache eviction strategies, and optional compression. """

import bz2
import collections
import enum
import functools
import inspect
import logging
import lzma
import os
import queue
import sqlite3
import tempfile
import threading
import zlib


Compression = enum.Enum("Compression", ("DEFLATE", "BZIP2", "LZMA"))
CachingStrategy = enum.Enum("CachingStrategy", ("FIFO", "LRU"))


class WebCache:

  cache_file_stats_displayed = set()

  def __init__(self, table_name, *, caching_strategy, expiration=None, db_filepath=None, db_filename=None,
               compression=None, compression_level=9, logger=None, safe_mode=False):
    """
    Args:
      table_name: Database table name used for the cache
      caching_strategy: CachingStrategy enum defining how cache entries are removed
      expiration: Cache item lifetime in seconds, used to clean items with the FIFO strategy, or None if items never
        expire
      db_filepath: Database filepath. If None, will generate a file in /var/tmp, or default system temp dir
      db_filename: Database filename. If None, will generate a filename according to the calling script name
      compression: Algorithm used to compress cache items, or None for no compression
      compression_level: Compression level (0-9)
      logger: Logger (as in the logging module) to log execution, or None for no logging
      safe_mode: If True, will enable some optimizations that increase cache write speed, but may compromise cache
        integrity in case of Python crash or power loss
    """
    # attribs
    self.__table_name = table_name
    self.__caching_strategy = caching_strategy
    self.__expiration = expiration
    self.__compression = compression
    self.__compression_level = compression_level
    self.__logger = logger
    # connexion
    if db_filepath is None:
      if db_filename is None:
        cache_filename = "%s-cache.sqlite" % (os.path.splitext(os.path.basename(inspect.getfile(inspect.stack()[-1][0])))[0])
      else:
        cache_filename = db_filename
      # prefer /var/tmp to /tmp because /tmp is usually wiped out at every boot (or a tmpfs mount) in most Linux distros
      cache_directory = "/var/tmp" if os.path.isdir("/var/tmp") else tempfile.gettempdir()
      db_filepath = os.path.join(cache_directory, cache_filename)
    self.__connexion = sqlite3.connect(db_filepath)
    # create table if necessary
    with self.__connexion:
      if not safe_mode:
        # enable some optimizations that can cause data corruption in case of power loss or python crash
        self.__connexion.executescript("""PRAGMA journal_mode = MEMORY;
                                          PRAGMA synchronous = OFF;""")
      self.__connexion.execute("CREATE TABLE IF NOT EXISTS %s (url TEXT PRIMARY KEY, added_timestamp INTEGER NOT NULL, last_accessed_timestamp INTEGER NOT NULL, data BLOB NOT NULL);" % (self.__table_name))
    self.purge()
    # stats
    if (self.__logger is not None) and self.__logger.isEnabledFor(logging.DEBUG):
      with self.__connexion:
        row_count = self.__connexion.execute("SELECT COUNT(*) FROM %s;" % (self.__table_name)).fetchall()[0][0]
      self.__logger.debug("Cache '%s' contains %u entries" % (self.__table_name, row_count))
      if db_filepath not in __class__.cache_file_stats_displayed:
        __class__.cache_file_stats_displayed.add(db_filepath)
        size = os.path.getsize(db_filepath)
        if size > 1000000000:
          size = "%0.2fGB" % (size / 1000000000)
        elif size > 1000000:
          size = "%0.2fMB" % (size / 1000000)
        elif size > 1000:
          size = "%uKB" % (size // 1000)
        else:
          size = "%uB" % (size)
        self.__logger.debug("Total size of file '%s': %s" % (db_filepath, size))
    self.hit_count = 0
    self.miss_count = 0

  def __del__(self):
    self.__connexion.close()

  def __getitem__(self, url):
    """ Get an item from cache. """
    with self.__connexion:
      data = self.__connexion.execute("SELECT data FROM %s WHERE url = ?;" % (self.__table_name), (url,)).fetchone()[0]
    if self.__compression is Compression.DEFLATE:
      buffer = memoryview(data)
      data = zlib.decompress(buffer)
    elif self.__compression is Compression.BZIP2:
      buffer = memoryview(data)
      data = bz2.decompress(buffer)
    elif self.__compression is Compression.LZMA:
      buffer = memoryview(data)
      data = lzma.decompress(buffer)
    if self.__caching_strategy is CachingStrategy.LRU:
      # update last access time
      with self.__connexion:
        self.__connexion.execute("UPDATE " +
                                 self.__table_name +
                                 " SET last_accessed_timestamp = strftime('%s', 'now') WHERE url = ?;", (url,))
    return data

  def __setitem__(self, url, data):
    """ Store an item in cache. """
    if self.__compression is Compression.DEFLATE:
      buffer = memoryview(data)
      data = zlib.compress(buffer, self.__compression_level)
    elif self.__compression is Compression.BZIP2:
      buffer = memoryview(data)
      data = bz2.compress(buffer, compresslevel=self.__compression_level)
    elif self.__compression is Compression.LZMA:
      buffer = memoryview(data)
      data = lzma.compress(buffer, format=lzma.FORMAT_ALONE, preset=self.__compression_level)
    with self.__connexion:
      self.__connexion.execute("INSERT OR REPLACE INTO " +
                               self.__table_name +
                               " (url, added_timestamp, last_accessed_timestamp,data) VALUES (?, strftime('%s','now'), strftime('%s','now'), ?);",
                               (url, sqlite3.Binary(data)))

  def __delattr__(self, url):
    """ Remove an item from cache. """
    with self.__connexion:
      self.__connexion.execute("DELETE FROM " + self.__table_name + " WHERE url = ?;", (url,))

  def purge(self):
    """ Purge cache by removing obsolete items. """
    if self.__expiration is not None:
      with self.__connexion:
        if self.__caching_strategy is CachingStrategy.FIFO:
          # dump least recently added rows
          purged_count = self.__connexion.execute("DELETE FROM " +
                                                  self.__table_name +
                                                  " WHERE (strftime('%s', 'now') - added_timestamp) > ?;",
                                                  (self.__expiration,)).rowcount
        elif self.__caching_strategy is CachingStrategy.LRU:
          # dump least recently accessed rows
          purged_count = self.__connexion.execute("DELETE FROM " +
                                                  self.__table_name +
                                                  " WHERE (strftime('%s', 'now') - last_accessed_timestamp) > ?;",
                                                  (self.__expiration,)).rowcount
      if self.__logger is not None:
        self.__logger.debug("%u obsolete entries have been removed from cache '%s'" % (purged_count, self.__table_name))

  def __contains__(self, url):
    """ Return true if an item is present in cache for that url, False instead. """
    with self.__connexion:
      hit = (self.__connexion.execute("SELECT COUNT(*) FROM %s WHERE url = ?;" % (self.__table_name),
                                      (url,)).fetchall()[0][0] > 0)
    if hit:
      self.hit_count += 1
    else:
      self.miss_count += 1
    return hit


class ThreadedWebCache:

  """
  Similar to WebCache, but delegate all sqlite3 calls to a dedicated thread.

  This allows getting rid of the 'same thread' sqlite3 module limitation.
  Caller thread send calls in the execute queue and get the results in the result queue.
  All calls are blocking and synchronous.

  """

  def __init__(self, *args, **kwargs):
    self.thread = WebCacheThread()
    self.thread.execute_queue.put_nowait((args, kwargs))
    self.thread.start()

  def waitResult(self):
    return self.thread.result_queue[threading.get_ident()].get()

  def __getitem__(self, *args, **kwargs):
    self.thread.execute_queue.put_nowait((threading.get_ident(), WebCache.__getitem__, args, kwargs))
    return self.waitResult()

  def __setitem__(self, *args, **kwargs):
    self.thread.execute_queue.put_nowait((threading.get_ident(), WebCache.__setitem__, args, kwargs))
    return self.waitResult()

  def __delattr__(self, *args, **kwargs):
    self.thread.execute_queue.put_nowait((threading.get_ident(), WebCache.__delattr__, args, kwargs))
    return self.waitResult()

  def purge(self, *args, **kwargs):
    self.thread.execute_queue.put_nowait((threading.get_ident(), WebCache.purge, args, kwargs))
    return self.waitResult()

  def __contains__(self, *args, **kwargs):
    self.thread.execute_queue.put_nowait((threading.get_ident(), WebCache.__contains__, args, kwargs))
    return self.waitResult()


class WebCacheThread(threading.Thread):

  """ Thread executing all sqlite3 calls for the ThreadedWebCache class. """

  def __init__(self):
    self.execute_queue = queue.Queue()
    self.result_queue = collections.defaultdict(functools.partial(queue.Queue, maxsize=1))
    super().__init__(name=__class__.__name__, daemon=True)

  def run(self):
    args, kwargs = self.execute_queue.get_nowait()
    cache_obj = WebCache(*args, **kwargs)
    while True:
      thread_id, method, args, kwargs = self.execute_queue.get()
      result = method(cache_obj, *args, **kwargs)
      self.result_queue[thread_id].put_nowait(result)
