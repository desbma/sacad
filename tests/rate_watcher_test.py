#!/usr/bin/env python3

""" Unit tests for rate watcher. """

import os
import tempfile
import time
import unittest

from sacad.rate_watcher import AccessRateWatcher

from . import sched_and_run

ALMOST_NO_TIME = 0.05


class TestRateWatcher(unittest.TestCase):

    """Test suite for rate watcher."""

    def test_minDelayBetweenAccesses(self):
        """Test rate limit."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_filepath = os.path.join(tmp_dir, "db.sqlite")
            sched_and_run(
                AccessRateWatcher(
                    db_filepath, "http://1.domain.com/abcd", min_delay_between_accesses=1
                ).waitAccessAsync()
            )
            time_first_access_domain1 = time.monotonic()

            sched_and_run(
                AccessRateWatcher(
                    db_filepath, "http://2.domain.com/efgh", min_delay_between_accesses=1
                ).waitAccessAsync()
            )
            time_first_access_domain2 = time.monotonic()
            self.assertAlmostEqual(time_first_access_domain2, time_first_access_domain1, delta=ALMOST_NO_TIME)

            before = time.monotonic()
            sched_and_run(
                AccessRateWatcher(
                    db_filepath, "http://1.domain.com/ijkl", min_delay_between_accesses=1
                ).waitAccessAsync()
            )
            after = time.monotonic()
            self.assertAlmostEqual(after - before, 1, delta=ALMOST_NO_TIME)

            before = time.monotonic()
            sched_and_run(
                AccessRateWatcher(
                    db_filepath, "http://2.domain.com/mnop", min_delay_between_accesses=2
                ).waitAccessAsync()
            )
            after = time.monotonic()
            self.assertAlmostEqual(after - before, 1, delta=ALMOST_NO_TIME)

            before = time.monotonic()
            sched_and_run(
                AccessRateWatcher(
                    db_filepath, "http://2.domain.com/qrst", min_delay_between_accesses=2
                ).waitAccessAsync()
            )
            after = time.monotonic()
            self.assertAlmostEqual(after - before, 2, delta=ALMOST_NO_TIME)

            time.sleep(1)
            before = time.monotonic()
            sched_and_run(
                AccessRateWatcher(
                    db_filepath, "http://2.domain.com/ufwx", min_delay_between_accesses=1
                ).waitAccessAsync()
            )
            after = time.monotonic()
            self.assertAlmostEqual(after - before, 0, delta=ALMOST_NO_TIME)


if __name__ == "__main__":
    # run tests
    unittest.main()
