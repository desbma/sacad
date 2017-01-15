#!/usr/bin/env python3

import os
import tempfile
import time
import unittest

from sacad.rate_watcher import AccessRateWatcher, WaitNeeded


class TestRateWatcher(unittest.TestCase):

  def test_minDelayBetweenAccesses(self):
    with tempfile.TemporaryDirectory() as tmp_dir:
      db_filepath = os.path.join(tmp_dir, "db.sqlite")
      with AccessRateWatcher(db_filepath,
                             "http://1.domain.com/abcd",
                             min_delay_between_accesses=1):
        time_first_access_domain1 = time.time()

      with AccessRateWatcher(db_filepath,
                             "http://2.domain.com/abcd",
                             min_delay_between_accesses=1):
        time_first_access_domain2 = time.time()
      self.assertLess(time_first_access_domain2 - time_first_access_domain1, 1)

      with self.assertRaises(WaitNeeded) as cm:
        with AccessRateWatcher(db_filepath,
                               "http://1.domain.com/efgh",
                               min_delay_between_accesses=1):
          pass
      self.assertGreaterEqual(cm.exception.wait_s + 0.1, 1)

      with self.assertRaises(WaitNeeded) as cm:
        with AccessRateWatcher(db_filepath,
                               "http://2.domain.com/efgh",
                               min_delay_between_accesses=1):
          pass
      self.assertGreaterEqual(cm.exception.wait_s + 0.1, 1)

      with self.assertRaises(WaitNeeded) as cm:
        with AccessRateWatcher(db_filepath,
                               "http://2.domain.com/ijkl",
                               min_delay_between_accesses=2):
          pass
      self.assertGreaterEqual(cm.exception.wait_s + 0.1, 2)

      time.sleep(1)
      with AccessRateWatcher(db_filepath,
                             "http://2.domain.com/efgh",
                             min_delay_between_accesses=1):
        pass


if __name__ == "__main__":
  # run tests
  unittest.main()
