""" This module provides a class with a context manager to help avoid overloading web servers. """

import collections
import logging
import os
import sqlite3
import threading
import time
import urllib.parse

import lockfile


MIN_WAIT_TIME_S = 0.01
SUSPICIOUS_LOCK_AGE_S = 120


class WaitNeeded(Exception):

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
    """ Get lock or raise WaitNeeded exception. """
    for try_lock in (True, False):
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

      if try_lock:
        locked = self._getLock()
        if locked:
          break
        # loop again to find wait time
      else:
        raise WaitNeeded(MIN_WAIT_TIME_S)

  def _getLock(self):
    with __class__.thread_dict_lock:
      tlock = __class__.thread_locks[self.domain]
    if tlock.acquire(blocking=False):
      plock = lockfile.FileLock(os.path.join(self.lock_dir, self.domain))
      try:
        plock.acquire(timeout=0)
      except (lockfile.LockTimeout, lockfile.AlreadyLocked):
        # detect and break locks of dead processes
        lock_age = time.time() - os.path.getmtime(plock.lock_file)
        if lock_age > SUSPICIOUS_LOCK_AGE_S:
          logging.getLogger().warning("Breaking suspicious lock '%s' created %.2f seconds ago" % (plock.lock_file,
                                                                                                  lock_age))
          plock.break_lock()
        tlock.release()
      except:
        tlock.release()
        raise
      else:
        return True
    else:
      # lock not available: wait for it, release it immediately and return as if locking fails
      # we do this to wait for the right amount of time but still re-read the cache
      with tlock:
        pass
    return False

  def _releaseLock(self):
    lockfile.FileLock(os.path.join(self.lock_dir, self.domain)).release()
    __class__.thread_locks[self.domain].release()
