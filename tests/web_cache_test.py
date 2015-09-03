#!/usr/bin/env python3

import collections
import logging
import os
import pickle
import random
import string
import sys
import time
import unittest

import sacad.mkstemp_ctx as mkstemp_ctx
import sacad.web_cache as web_cache


web_cache.DISABLE_PERSISTENT_CACHING = True

INFINITY = sys.maxsize


def get_random_string(length, chars=string.ascii_letters + string.digits):
  return "".join(random.choice(chars) for _ in range(length))


class TestWebCache(unittest.TestCase):

  def test_getSetDelete(self):
    """ Get/set/delete cache items using all cache parameter combinations. """
    for cache_class in (web_cache.WebCache, web_cache.ThreadedWebCache):
      for compression in web_cache.Compression:
        for compression_level in range(1, 9):
          for caching_strategy in web_cache.CachingStrategy:
            for expiration in (None, 0, INFINITY):
              for sql_crash_safe in (True, False):
                table_name = get_random_string(16, string.ascii_letters)
                with mkstemp_ctx.mkstemp(suffix=".sqlite") as cache_filepath:
                  # init cache
                  cache = cache_class(cache_filepath,
                                      table_name,
                                      caching_strategy=caching_strategy,
                                      expiration=expiration,
                                      compression=compression,
                                      compression_level=compression_level,
                                      safe_mode=sql_crash_safe)
                  already_used_keys = set()
                  item_count = 0

                  for req_type in ("get", "post"):
                    for item_count in range(item_count + 1, item_count + 4):
                      while True:
                        # generate cache key
                        key = get_random_string(16)
                        if req_type == "post":
                          key = key, collections.OrderedDict(((k, v) for k, v in zip((get_random_string(8) for _ in range(4)),
                                                                                     (get_random_string(16) for _ in range(4)))))

                        # ensure key is unique for this cache
                        bin_key = pickle.dumps(key)
                        if bin_key not in already_used_keys:
                          already_used_keys.add(bin_key)
                          break

                      # generate cache data
                      data = os.urandom(2 ** 13)

                      # check cache size
                      self.assertEqual(len(cache), item_count - 1)

                      # check key is not in cache
                      self.assertNotIn(key, cache)
                      with self.assertRaises(KeyError):
                        cache[key]
                      with self.assertRaises(KeyError):
                        del cache[key]

                      # add data to cache
                      cache[key] = data

                      # check key is in cache
                      self.assertIn(key, cache)
                      self.assertEqual(cache[key], data)

                      # check cache size
                      self.assertEqual(len(cache), item_count)

                      # delete cache item
                      del cache[key]

                      # check it is not in cache anymore
                      self.assertNotIn(key, cache)
                      with self.assertRaises(KeyError):
                        cache[key]
                      with self.assertRaises(KeyError):
                        del cache[key]

                      # check cache size
                      self.assertEqual(len(cache), item_count - 1)

                      # check other keys are still here
                      for old_key in map(pickle.loads, already_used_keys):
                        if old_key != key:
                          self.assertIn(old_key, cache)

                      # add cache item again
                      cache[key] = data

  def test_getCacheHitStats(self):
    """ Get cache stats using all cache parameter combinations. """
    for cache_class in (web_cache.WebCache, web_cache.ThreadedWebCache):
      for compression in web_cache.Compression:
        for compression_level in range(1, 9):
          for caching_strategy in web_cache.CachingStrategy:
            for expiration in (None, 0, INFINITY):
              for sql_crash_safe in (True, False):
                table_name = get_random_string(16, string.ascii_letters)
                with mkstemp_ctx.mkstemp(suffix=".sqlite") as cache_filepath:
                  # init cache
                  cache = cache_class(cache_filepath,
                                      table_name,
                                      caching_strategy=caching_strategy,
                                      expiration=expiration,
                                      compression=compression,
                                      compression_level=compression_level,
                                      safe_mode=sql_crash_safe)

                  i = 0
                  for req_type in ("get", "post"):
                    for i in range(i + 1, 5):
                      # generate item
                      key = "%s_%u" % (req_type, i)
                      if req_type == "post":
                        key = key, collections.OrderedDict(((k, v) for k, v in zip((get_random_string(4) for _ in range(2)),
                                                                                   (get_random_string(8) for _ in range(2)))))
                      data = os.urandom(2 ** 13)

                      # add item
                      cache[key] = data

                      # check cache hit stats
                      self.assertEqual(cache.getCacheHitStats(), (i - 1, i - 1))
                      self.assertIn(key, cache)
                      self.assertEqual(cache.getCacheHitStats(), (i, i - 1))
                      self.assertNotIn("(o_o)", cache)
                      self.assertEqual(cache.getCacheHitStats(), (i, i))

  def test_purge(self):
    """ Purge obsolete cache entries. """
    for cache_class in (web_cache.WebCache, web_cache.ThreadedWebCache):
      for caching_strategy in web_cache.CachingStrategy:
        for expiration in (None, 2, INFINITY):
          table_name = get_random_string(16, string.ascii_letters)
          with mkstemp_ctx.mkstemp(suffix=".sqlite") as cache_filepath:
            # init cache
            cache = cache_class(cache_filepath,
                                table_name,
                                caching_strategy=caching_strategy,
                                expiration=expiration)

            # add items
            for req_type in ("get", "post"):
              for i in range(5):
                key = "%s_%u" % (req_type, i)
                if req_type == "post":
                  key = key, collections.OrderedDict(((k, v) for k, v in zip((get_random_string(4) for _ in range(2)),
                                                                             (get_random_string(8) for _ in range(2)))))
                data = os.urandom(2 ** 13)
                cache[key] = data

            # purge
            purged_count = cache.purge()
            if expiration and (expiration != INFINITY):
              # before expiration, nothing should have been purged
              time.sleep(1)
              self.assertEqual(purged_count, 0)
              self.assertEqual(len(cache), 10)
              # wait for expiration
              time.sleep(expiration)
              # after expiration, all should have been purged
              purged_count = cache.purge()
              self.assertEqual(purged_count, 10)
              self.assertEqual(len(cache), 0)
            else:
              # nothing should have been purged
              self.assertEqual(purged_count, 0)
              self.assertEqual(len(cache), 10)


if __name__ == "__main__":
  # disable logging
  logging.basicConfig(level=logging.CRITICAL + 1)

  # run tests
  unittest.main()
