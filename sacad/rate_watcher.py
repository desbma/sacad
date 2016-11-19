""" This module provides a class with a context manager to help avoid overloading web servers. """

import collections
import logging
import os
import sqlite3
import threading
import time
import urllib.parse

import lockfile


SUSPICIOUS_LOCK_AGE_S = 120
DEBUG_LOCKING = False


class RetryNeeded(Exception):

  """ Exception raised when access can not be granted, and call should be retried. """

  pass


class WaitNeeded(RetryNeeded):

  """ Exception raised when access can not be granted without waiting. """

  def __init__(self, wait_time_s):
    self.wait_s = wait_time_s


class AccessRateWatcher:

  """ Access rate limiter, supporting concurrent access by threads and/or processes. """

  thread_locks = collections.defaultdict(threading.Lock)
  thread_dict_lock = threading.Lock()

  def __init__(self, db_filepath, url, min_delay_between_accesses):
    self.domain = urllib.parse.urlsplit(url).netloc
    self.min_delay_between_accesses = min_delay_between_accesses
    os.makedirs(os.path.dirname(db_filepath), exist_ok=True)
    self.connection = sqlite3.connect(db_filepath)
    with self.connection:
      self.connection.executescript("""PRAGMA journal_mode = MEMORY;
                                       PRAGMA synchronous = OFF;
                                       CREATE TABLE IF NOT EXISTS access_timestamp (domain TEXT PRIMARY KEY,
                                                                                    timestamp FLOAT NOT NULL);""")
    self.lock_dir = os.path.join(os.path.dirname(db_filepath), "plocks")
    os.makedirs(self.lock_dir, exist_ok=True)

  def __enter__(self):
    self._raiseOrLock()
    self._access()

  def __exit__(self, exc_type, exc_value, traceback):
    self._releaseLock()

  def _access(self):
    """ Notify the watcher that the server is accessed. """
    with self.connection:
      self.connection.execute("""INSERT OR REPLACE INTO access_timestamp
                                (domain, timestamp) VALUES (?, ?)""",
                              (self.domain, time.time(),))

  def _raiseOrLock(self):
    """ Get lock or raise WaitNeeded or RetryNeeded exception. """
    with self.connection:
      last_access_time = self.connection.execute("""SELECT timestamp
                                                    FROM access_timestamp
                                                    WHERE domain = ?;""",
                                                 (self.domain,)).fetchone()
    if last_access_time is not None:
      last_access_time = last_access_time[0]
      now = time.time()
      time_since_last_access = now - last_access_time
      if time_since_last_access < self.min_delay_between_accesses:
        time_to_wait = self.min_delay_between_accesses - time_since_last_access
        raise WaitNeeded(time_to_wait)

    locked = self._getLock()
    if not locked:
      raise RetryNeeded()

  def _getLock(self):
    with __class__.thread_dict_lock:
      tlock = __class__.thread_locks[self.domain]
    if tlock.acquire(blocking=False):
      if DEBUG_LOCKING:
        logging.getLogger().debug("Got thread lock for domain '%s'" % (self.domain))
      plock = lockfile.FileLock(os.path.join(self.lock_dir, self.domain))
      try:
        plock.acquire(timeout=0)
      except (lockfile.LockTimeout, lockfile.AlreadyLocked):
        if DEBUG_LOCKING:
          logging.getLogger().debug("Failed to get process lock for domain '%s'" % (self.domain))
        # detect and break locks of dead processes
        lock_age = time.time() - os.path.getmtime(plock.lock_file)
        if lock_age > SUSPICIOUS_LOCK_AGE_S:
          logging.getLogger().warning("Breaking suspicious lock '%s' created %.2f seconds ago" % (plock.lock_file,
                                                                                                  lock_age))
          plock.break_lock()
        else:
          # lock not available: wait for it, release it immediately and return as if locking fails
          # we do this to wait for the right amount of time but still re-read the cache
          with plock:
            pass
        tlock.release()
      except:
        tlock.release()
        raise
      else:
        if DEBUG_LOCKING:
          logging.getLogger().debug("Got process lock for domain '%s'" % (self.domain))
        return True
    else:
      if DEBUG_LOCKING:
        logging.getLogger().debug("Failed to get thread lock for domain '%s'" % (self.domain))
      # lock not available: wait for it, release it immediately and return as if locking fails
      # we do this to wait for the right amount of time but still re-read the cache
      with tlock:
        pass
    return False

  def _releaseLock(self):
    lockfile.FileLock(os.path.join(self.lock_dir, self.domain)).release()
    __class__.thread_locks[self.domain].release()
