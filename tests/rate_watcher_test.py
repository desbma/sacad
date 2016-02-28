#!/usr/bin/env python3

import logging
import os
import tempfile
import time
import unittest

from sacad.rate_watcher import AccessRateWatcher


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
      with AccessRateWatcher(db_filepath,
                             "http://1.domain.com/efgh",
                             min_delay_between_accesses=1):
        time_second_access_domain1 = time.time()
      self.assertGreater(time_second_access_domain1 - time_first_access_domain1, 1)
      with AccessRateWatcher(db_filepath,
                             "http://2.domain.com/efgh",
                             min_delay_between_accesses=1):
        time_second_access_domain2 = time.time()
      self.assertLess(time_second_access_domain2 - time_second_access_domain1, 1)
      with AccessRateWatcher(db_filepath,
                             "http://2.domain.com/ijkl",
                             min_delay_between_accesses=2):
        time_third_access_domain2 = time.time()
      self.assertGreater(time_third_access_domain2 - time_second_access_domain2, 2)


if __name__ == "__main__":
  # disable logging
  logging.basicConfig(level=logging.CRITICAL + 1)

  # run tests
  unittest.main()
