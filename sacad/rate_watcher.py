""" This module provides a class with a context manager to help avoid overloading web servers. """

import asyncio
import logging
import os
import random
import sqlite3
import time
import urllib.parse


class AccessRateWatcher:

  """ Access rate limiter, supporting concurrent access by threads and/or processes. """

  def __init__(self, db_filepath, url, min_delay_between_accesses, *, jitter_range_ms=None, logger=logging.getLogger()):
    self.domain = urllib.parse.urlsplit(url).netloc
    self.min_delay_between_accesses = min_delay_between_accesses
    self.jitter_range_ms = jitter_range_ms
    self.logger = logger
    os.makedirs(os.path.dirname(db_filepath), exist_ok=True)
    self.connection = sqlite3.connect(db_filepath)
    with self.connection:
      self.connection.executescript("""CREATE TABLE IF NOT EXISTS access_timestamp (domain TEXT PRIMARY KEY,
                                                                                    timestamp FLOAT NOT NULL);""")
    self.lock = None

  async def waitAccessAsync(self):
    """ Wait the needed time before sending a request to honor rate limit. """
    if self.lock is None:
      self.lock = asyncio.Lock()

    async with self.lock:
      while True:
        last_access_ts = self.__getLastAccess()
        if last_access_ts is not None:
          now = time.time()
          last_access_ts = last_access_ts[0]
          time_since_last_access = now - last_access_ts
          if time_since_last_access < self.min_delay_between_accesses:
            time_to_wait = self.min_delay_between_accesses - time_since_last_access
            if self.jitter_range_ms is not None:
              time_to_wait += random.randint(*self.jitter_range_ms) / 1000
            self.logger.debug("Sleeping for %.2fms because of rate limit for domain %s" % (time_to_wait * 1000,
                                                                                           self.domain))
            await asyncio.sleep(time_to_wait)

        access_time = time.time()
        self.__access(access_time)

        # now we should be good... except if another process did the same query at the same time
        # the database serves as an atomic lock, query again to be sure the last row is the one
        # we just inserted
        last_access_ts = self.__getLastAccess()
        if last_access_ts[0] == access_time:
          break

  def __getLastAccess(self):
    with self.connection:
      return self.connection.execute("""SELECT timestamp
                                        FROM access_timestamp
                                        WHERE domain = ?;""",
                                     (self.domain,)).fetchone()

  def __access(self, ts):
    """ Record an API access. """
    with self.connection:
      self.connection.execute("INSERT OR REPLACE INTO access_timestamp (timestamp, domain) VALUES (?, ?)",
                              (ts, self.domain))
