""" This module provides classes with context managers to help avoid overloading a web API. """

import sqlite3
import time


class ApiAccessRateWatcher:

  def __init__(self, logger, db_filepath=":memory:", min_delay_between_accesses=None, max_accesses_per_day=None):
    self.logger = logger
    self.min_delay_between_accesses = min_delay_between_accesses
    self.max_accesses_per_day = max_accesses_per_day
    self.connexion = sqlite3.connect(db_filepath)
    with self.connexion:
      self.connexion.executescript("""PRAGMA journal_mode = MEMORY;
                                      PRAGMA synchronous = OFF;
                                      CREATE TABLE IF NOT EXISTS access_timestamp (timestamp FLOAT NOT NULL);""")
      self.connexion.execute("DELETE FROM access_timestamp WHERE (strftime('%s', 'now') - timestamp) > 86400;")
    self.time_sleeping = 0

  def __enter__(self):
    self.waitAccess()

  def __exit__(self, exc_type, exc_value, traceback):
    self.access()

  def access(self):
    """ Notify the watcher that the API is accessed. """
    with self.connexion:
      self.connexion.execute("INSERT INTO access_timestamp (timestamp) VALUES (?)", (time.time(),))

  def waitAccess(self, timeout=None):
    """ Wait the needed time before sending a request to honor rate limit. Return False if timeout, True otherwise. """
    if self.max_accesses_per_day is not None:
      # daily quota
      now = time.time()
      one_day = 60 * 60 * 24
      one_day_ago = now - one_day
      with self.connexion:
        req_result = self.connexion.execute("""SELECT timestamp
                                               FROM access_timestamp
                                               WHERE timestamp > ?
                                               ORDER BY timestamp DESC
                                               LIMIT 1
                                               OFFSET ?;""",
                                            (one_day_ago,
                                             self.max_accesses_per_day - 1)).fetchone()
      if req_result:
        time_to_wait = req_result[0] - one_day_ago
        if (timeout is not None) and (time_to_wait >= timeout):
          return False
        self.logger.warning("Sleeping for %us because of daily quota" % (time_to_wait))
        self.time_sleeping += time_to_wait
        time.sleep(time_to_wait)

    if self.min_delay_between_accesses is not None:
      # rate limit
      with self.connexion:
        req_result = self.connexion.execute("""SELECT timestamp
                                               FROM access_timestamp
                                               ORDER BY timestamp DESC
                                               LIMIT 1;""").fetchone()
      if req_result:
        now = time.time()
        last_access_time = req_result[0]
        time_since_last_access = now - last_access_time
        if time_since_last_access < self.min_delay_between_accesses:
          time_to_wait = self.min_delay_between_accesses - time_since_last_access
          if (timeout is not None) and (time_to_wait >= timeout):
            return False
          self.logger.debug("Sleeping for %.2fms because of rate limit" % (time_to_wait * 1000))
          self.time_sleeping += time_to_wait
          time.sleep(time_to_wait)

    return True
