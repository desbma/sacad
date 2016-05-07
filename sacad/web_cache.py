""" Persistent cache storage for web ressources, with different cache eviction strategies, and optional compression. """

import bz2
import collections
import enum
import functools
import inspect
import lzma
import os
import pickle
import queue
import sqlite3
import threading
import zlib


DISABLE_PERSISTENT_CACHING = False  # useful for tests


Compression = enum.Enum("Compression", ("NONE", "DEFLATE", "BZIP2", "LZMA"))
CachingStrategy = enum.Enum("CachingStrategy", ("FIFO", "LRU"))


class WebCache:

  def __init__(self, db_filepath, table_name, *, caching_strategy, expiration=None, compression=Compression.NONE,
               compression_level=9, safe_mode=False):
    """
    Args:
      db_filepath: Database filepath
      table_name: Database table name used for the cache
      caching_strategy: CachingStrategy enum defining how cache entries are removed
      expiration: Cache item lifetime in seconds, used to clean items with the FIFO and LRU strateges, or None if items
        never expire
      compression: Algorithm used to compress cache items
      compression_level: Compression level (0-9)
      safe_mode: If False, will enable some optimizations that increase cache write speed, but may compromise cache
        integrity in case of Python crash or power loss
    """
    # attribs
    self.__table_name = table_name
    assert(caching_strategy in CachingStrategy)
    self.__caching_strategy = caching_strategy
    self.__expiration = expiration
    assert(compression in Compression)
    self.__compression = compression
    self.__compression_level = compression_level

    # connection
    if DISABLE_PERSISTENT_CACHING:
      self.__connection = sqlite3.connect(":memory:")
    else:
      self.__db_filepath = db_filepath
      self.__connection = sqlite3.connect(self.__db_filepath)

    # create tables if necessary
    with self.__connection:
      if not safe_mode:
        # enable some optimizations that can cause data corruption in case of power loss or python crash
        self.__connection.executescript("""PRAGMA journal_mode = MEMORY;
                                           PRAGMA synchronous = OFF;""")
      self.__connection.execute("""CREATE TABLE IF NOT EXISTS %s
                                   (
                                     url TEXT PRIMARY KEY,
                                     added_timestamp INTEGER NOT NULL,
                                     last_accessed_timestamp INTEGER NOT NULL,
                                     data BLOB NOT NULL
                                   );""" % (self.__table_name))
      self.__connection.execute("""CREATE TABLE IF NOT EXISTS %s_post
                                   (
                                     url TEXT NOT NULL,
                                     post_data BLOB NOT NULL,
                                     added_timestamp INTEGER NOT NULL,
                                     last_accessed_timestamp INTEGER NOT NULL,
                                     data BLOB NOT NULL
                                   );""" % (self.__table_name))
      self.__connection.execute("CREATE INDEX IF NOT EXISTS idx ON %s_post(url, post_data);" % (self.__table_name))

    # stats
    self.__hit_count = 0
    self.__miss_count = 0

  def getDatabaseFileSize(self):
    """ Return the file size of the database as a pretty string. """
    if DISABLE_PERSISTENT_CACHING:
      return "?"
    size = os.path.getsize(self.__db_filepath)
    if size > 1000000000:
      size = "%0.3fGB" % (size / 1000000000)
    elif size > 1000000:
      size = "%0.2fMB" % (size / 1000000)
    elif size > 1000:
      size = "%uKB" % (size // 1000)
    else:
      size = "%uB" % (size)
    return size

  def getCacheHitStats(self):
    return self.__hit_count, self.__miss_count

  def __len__(self):
    """ Return the number of items in the cache. """
    with self.__connection:
      row_count = self.__connection.execute("SELECT COUNT(*) FROM %s;" % (self.__table_name)).fetchall()[0][0]
      row_count += self.__connection.execute("SELECT COUNT(*) FROM %s_post;" % (self.__table_name)).fetchall()[0][0]
    return row_count

  def __del__(self):
    try:
      self.__connection.close()
    except AttributeError:
      pass

  def __getitem__(self, url_data):
    """ Get an item from cache. """
    if isinstance(url_data, tuple):
      url, post_data = url_data
    else:
      url = url_data
      post_data = None

    with self.__connection:
      if post_data is not None:
        post_bin_data = sqlite3.Binary(pickle.dumps(post_data, protocol=3))
        data = self.__connection.execute("""SELECT data
                                            FROM %s_post
                                            WHERE url = ? AND
                                                  post_data = ?;""" % (self.__table_name),
                                         (url, post_bin_data)).fetchone()
      else:
        data = self.__connection.execute("""SELECT data
                                            FROM %s
                                            WHERE url = ?;""" % (self.__table_name),
                                         (url,)).fetchone()
    if not data:
      raise KeyError(url_data)
    data = data[0]

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
      with self.__connection:
        if post_data is not None:
          self.__connection.execute("UPDATE " +
                                    self.__table_name +
                                    "_post SET last_accessed_timestamp = strftime('%s', 'now') WHERE url = ? AND post_data = ?;",
                                    (url, post_bin_data))
        else:
          self.__connection.execute("UPDATE " +
                                    self.__table_name +
                                    " SET last_accessed_timestamp = strftime('%s', 'now') WHERE url = ?;",
                                    (url,))
    return data

  def __setitem__(self, url_data, data):
    """ Store an item in cache. """
    if isinstance(url_data, tuple):
      url, post_data = url_data
    else:
      url = url_data
      post_data = None

    if self.__compression is Compression.DEFLATE:
      buffer = memoryview(data)
      data = zlib.compress(buffer, self.__compression_level)
    elif self.__compression is Compression.BZIP2:
      buffer = memoryview(data)
      data = bz2.compress(buffer, compresslevel=self.__compression_level)
    elif self.__compression is Compression.LZMA:
      buffer = memoryview(data)
      data = lzma.compress(buffer, format=lzma.FORMAT_ALONE, preset=self.__compression_level)

    with self.__connection:
      if post_data is not None:
        post_bin_data = sqlite3.Binary(pickle.dumps(post_data, protocol=3))
        self.__connection.execute("INSERT OR REPLACE INTO " +
                                  self.__table_name +
                                  "_post (url, post_data, added_timestamp, last_accessed_timestamp,data) VALUES (?, ?, strftime('%s','now'), strftime('%s','now'), ?);",
                                  (url, post_bin_data, sqlite3.Binary(data)))
      else:
        self.__connection.execute("INSERT OR REPLACE INTO " +
                                  self.__table_name +
                                  " (url, added_timestamp, last_accessed_timestamp,data) VALUES (?, strftime('%s','now'), strftime('%s','now'), ?);",
                                  (url, sqlite3.Binary(data)))

  def __delitem__(self, url_data):
    """ Remove an item from cache. """
    if isinstance(url_data, tuple):
      url, post_data = url_data
    else:
      url = url_data
      post_data = None

    with self.__connection:
      if post_data is not None:
        post_bin_data = sqlite3.Binary(pickle.dumps(post_data, protocol=3))
        deleted_count = self.__connection.execute("DELETE FROM " + self.__table_name + "_post " +
                                                  "WHERE url = ? AND post_data = ?;",
                                                  (url, post_bin_data)).rowcount
      else:
        deleted_count = self.__connection.execute("DELETE FROM " + self.__table_name + " WHERE url = ?;",
                                                  (url,)).rowcount
    if deleted_count == 0:
      raise KeyError(url_data)

  def purge(self):
    """ Purge cache by removing obsolete items. """
    purged_count = 0
    if self.__expiration is not None:
      with self.__connection:
        if self.__caching_strategy is CachingStrategy.FIFO:
          # dump least recently added rows
          for table_suffix in ("", "_post"):
            purged_count += self.__connection.execute("DELETE FROM " +
                                                      self.__table_name +
                                                      "%s " % (table_suffix) +
                                                      "WHERE (strftime('%s', 'now') - added_timestamp) > ?;",
                                                      (self.__expiration,)).rowcount
        elif self.__caching_strategy is CachingStrategy.LRU:
          # dump least recently accessed rows
          for table_suffix in ("", "_post"):
            purged_count += self.__connection.execute("DELETE FROM " +
                                                       self.__table_name +
                                                       "%s " % (table_suffix) +
                                                       "WHERE (strftime('%s', 'now') - last_accessed_timestamp) > ?;",
                                                       (self.__expiration,)).rowcount
    return purged_count

  def __contains__(self, url_data):
    """ Return true if an item is present in cache for that url, False instead. """
    if isinstance(url_data, tuple):
      url, post_data = url_data
    else:
      url = url_data
      post_data = None

    with self.__connection:
      if post_data is not None:
        post_bin_data = sqlite3.Binary(pickle.dumps(post_data, protocol=3))
        hit = (self.__connection.execute("""SELECT COUNT(*)
                                            FROM %s_post
                                            WHERE url = ? AND
                                                  post_data = ?;""" % (self.__table_name),
                                         (url, post_bin_data)).fetchall()[0][0] > 0)
      else:
        hit = (self.__connection.execute("""SELECT COUNT(*)
                                            FROM %s
                                            WHERE url = ?;""" % (self.__table_name),
                                         (url,)).fetchall()[0][0] > 0)
    if hit:
      self.__hit_count += 1
    else:
      self.__miss_count += 1
    return hit


class ThreadedWebCache:

  """
  Similar to WebCache, but delegate all sqlite3 calls to a dedicated thread.

  This allows getting rid of the 'same thread' sqlite3 module limitation.
  Caller thread send calls in the execute queue and get the results in the result queue.
  All calls are blocking and synchronous.

  """

  def __init__(self, *args, **kwargs):
    # this is the tricky part:
    # attach methods from WebCache, decorated by callToThread, to this object's class
    methods = inspect.getmembers(WebCache, inspect.isfunction)
    for method_name, method in methods:
      if method_name in ("__init__", "__del__"):
        continue
      new_method = __class__.callToThread(method)
      setattr(self.__class__, method_name, new_method)
    # start thread
    self.thread = WebCacheThread()
    self.thread.execute_queue.put_nowait((threading.get_ident(), args, kwargs))
    self.thread.start()
    self.thread.execute_queue.join()
    # check WebCache object construction went ok
    try:
      e = self.thread.exception_queue[threading.get_ident()].get_nowait()
    except queue.Empty:
      pass
    else:
      raise e

  def waitResult(self):
    """ Wait for the execution of the last enqueued job to be done, and return the result or raise an exception. """
    self.thread.execute_queue.join()
    try:
      e = self.thread.exception_queue[threading.get_ident()].get_nowait()
    except queue.Empty:
      return self.thread.result_queue[threading.get_ident()].get_nowait()
    else:
      raise e

  @staticmethod
  def callToThread(method):
    """ Wrap call to method to send it to WebCacheThread. """
    def func_wrapped(self, *args, **kwargs):
      self.thread.execute_queue.put_nowait((threading.get_ident(), method, args, kwargs))
      return self.waitResult()
    return func_wrapped


class WebCacheThread(threading.Thread):

  """ Thread executing all sqlite3 calls for the ThreadedWebCache class. """

  def __init__(self):
    self.execute_queue = queue.Queue()
    self.exception_queue = collections.defaultdict(functools.partial(queue.Queue, maxsize=1))
    self.result_queue = collections.defaultdict(functools.partial(queue.Queue, maxsize=1))
    super().__init__(name=__class__.__name__, daemon=True)

  def run(self):
    """ Thread loop. """
    # construct WebCache object locally
    thread_id, args, kwargs = self.execute_queue.get_nowait()
    try:
      cache_obj = WebCache(*args, **kwargs)
    except Exception as e:
      self.exception_queue[thread_id].put_nowait(e)
      loop = False
    else:
      loop = True
    self.execute_queue.task_done()

    # execute loop
    while loop:
      thread_id, method, args, kwargs = self.execute_queue.get()
      try:
        result = method(cache_obj, *args, **kwargs)
      except Exception as e:
        self.exception_queue[thread_id].put_nowait(e)
      else:
        self.result_queue[thread_id].put_nowait(result)
      self.execute_queue.task_done()
