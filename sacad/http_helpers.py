""" Common HTTP code. """

import asyncio
import logging
import os
import pickle

import aiohttp
import appdirs

from sacad import rate_watcher
from sacad import redo


def aiohttp_socket_timeout(socket_timeout_s):
  """ Return a aiohttp.ClientTimeout object with only socket timeouts set. """
  return aiohttp.ClientTimeout(total=None,
                               connect=None,
                               sock_connect=socket_timeout_s,
                               sock_read=socket_timeout_s)


IS_TRAVIS = os.getenv("CI") and os.getenv("TRAVIS")
HTTP_NORMAL_TIMEOUT = aiohttp_socket_timeout(30.1 if IS_TRAVIS else 9.1)
HTTP_SHORT_TIMEOUT = aiohttp_socket_timeout(12.1 if IS_TRAVIS else 3.1)
HTTP_MAX_ATTEMPTS = 6 if IS_TRAVIS else 3
HTTP_MAX_RETRY_SLEEP_S = 0 if IS_TRAVIS else 5
HTTP_MAX_RETRY_SLEEP_SHORT_S = 0 if IS_TRAVIS else 2
DEFAULT_USER_AGENT = "Mozilla/5.0"


class Http:

  def __init__(self, *, allow_session_cookies=False, min_delay_between_accesses=0, jitter_range_ms=None, logger=logging.getLogger()):
    self.allow_session_cookies = allow_session_cookies
    self.session = None
    self.watcher_db_filepath = os.path.join(appdirs.user_cache_dir(appname="sacad",
                                                                   appauthor=False),
                                            "rate_watcher.sqlite")
    self.min_delay_between_accesses = min_delay_between_accesses
    self.jitter_range_ms = jitter_range_ms
    self.logger = logger

  def __del__(self):
    if self.session is not None:
      asyncio.ensure_future(self.session.close())

  async def query(self, url, *, post_data=None, headers=None, verify=True, cache=None, pre_cache_callback=None):
    """ Send a GET/POST request or get data from cache, retry if it fails, and return a tuple of store in cache callback, response content. """
    async def store_in_cache_callback():
      pass
    if cache is not None:
      # try from cache first
      if post_data is not None:
        if (url, post_data) in cache:
          self.logger.debug("Got data for URL '%s' %s from cache" % (url, dict(post_data)))
          return store_in_cache_callback, cache[(url, post_data)]
      elif url in cache:
        self.logger.debug("Got data for URL '%s' from cache" % (url))
        return store_in_cache_callback, cache[url]

    if self.session is None:
      await self._initSession()

    domain_rate_watcher = rate_watcher.AccessRateWatcher(self.watcher_db_filepath,
                                                         url,
                                                         self.min_delay_between_accesses,
                                                         jitter_range_ms=self.jitter_range_ms,
                                                         logger=self.logger)

    for attempt, time_to_sleep in enumerate(redo.retrier(max_attempts=HTTP_MAX_ATTEMPTS,
                                                         sleeptime=1,
                                                         max_sleeptime=HTTP_MAX_RETRY_SLEEP_S,
                                                         sleepscale=1.5),
                                            1):
      await domain_rate_watcher.waitAccessAsync()

      try:
        if post_data is not None:
          async with self.session.post(url,
                                       data=post_data,
                                       headers=self._buildHeaders(headers),
                                       timeout=HTTP_NORMAL_TIMEOUT,
                                       ssl=verify) as response:
            content = await response.read()
        else:
          async with self.session.get(url,
                                      headers=self._buildHeaders(headers),
                                      timeout=HTTP_NORMAL_TIMEOUT,
                                      ssl=verify) as response:
            content = await response.read()

        if cache is not None:
          async def store_in_cache_callback():
            if pre_cache_callback is not None:
              # process
              try:
                data = await pre_cache_callback(content)
              except Exception:
                data = content
            else:
              data = content

            # add to cache
            if post_data is not None:
              cache[(url, post_data)] = data
            else:
              cache[url] = data

      except (asyncio.TimeoutError, aiohttp.ClientError) as e:
        self.logger.warning("Querying '%s' failed (attempt %u/%u): %s %s" % (url,
                                                                             attempt,
                                                                             HTTP_MAX_ATTEMPTS,
                                                                             e.__class__.__qualname__,
                                                                             e))
        if attempt == HTTP_MAX_ATTEMPTS:
          raise
        else:
          self.logger.debug("Retrying in %.3fs" % (time_to_sleep))
          await asyncio.sleep(time_to_sleep)

      else:
        break  # http retry loop

    response.raise_for_status()

    return store_in_cache_callback, content

  async def isReachable(self, url, *, headers=None, verify=True, response_headers=None, cache=None):
    """ Send a HEAD request with short timeout or get data from cache, return True if ressource has 2xx status code, False instead. """
    if (cache is not None) and (url in cache):
      # try from cache first
      self.logger.debug("Got headers for URL '%s' from cache" % (url))
      resp_ok, response_headers = pickle.loads(cache[url])
      return resp_ok

    if self.session is None:
      await self._initSession()

    domain_rate_watcher = rate_watcher.AccessRateWatcher(self.watcher_db_filepath,
                                                         url,
                                                         self.min_delay_between_accesses,
                                                         jitter_range_ms=self.jitter_range_ms,
                                                         logger=self.logger)
    resp_ok = True
    try:
      for attempt, time_to_sleep in enumerate(redo.retrier(max_attempts=HTTP_MAX_ATTEMPTS,
                                                           sleeptime=0.5,
                                                           max_sleeptime=HTTP_MAX_RETRY_SLEEP_SHORT_S,
                                                           sleepscale=1.5),
                                              1):
        await domain_rate_watcher.waitAccessAsync()

        try:
          async with self.session.head(url,
                                       headers=self._buildHeaders(headers),
                                       timeout=HTTP_SHORT_TIMEOUT,
                                       ssl=verify) as response:
            pass

        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
          self.logger.warning("Probing '%s' failed (attempt %u/%u): %s %s" % (url,
                                                                              attempt,
                                                                              HTTP_MAX_ATTEMPTS,
                                                                              e.__class__.__qualname__,
                                                                              e))
          if attempt == HTTP_MAX_ATTEMPTS:
            resp_ok = False
          else:
            self.logger.debug("Retrying in %.3fs" % (time_to_sleep))
            await asyncio.sleep(time_to_sleep)

        else:
          response.raise_for_status()

          if response_headers is not None:
            response_headers.update(response.headers)

          break  # http retry loop

    except aiohttp.ClientResponseError as e:
      self.logger.debug("Probing '%s' failed: %s %s" % (url, e.__class__.__qualname__, e))
      resp_ok = False

    if cache is not None:
      # store in cache
      cache[url] = pickle.dumps((resp_ok, response_headers))

    return resp_ok

  async def fastStreamedQuery(self, url, *, headers=None, verify=True):
    """ Send a GET request with short timeout, do not retry, and return streamed response. """
    if self.session is None:
      await self._initSession()

    response = await self.session.get(url,
                                      headers=self._buildHeaders(headers),
                                      timeout=HTTP_SHORT_TIMEOUT,
                                      ssl=verify)

    response.raise_for_status()

    return response

  def _buildHeaders(self, headers):
    """ Build HTTP headers dictionary. """
    if headers is None:
      headers = {}
    if "User-Agent" not in headers:
      headers["User-Agent"] = DEFAULT_USER_AGENT
    return headers

  async def _initSession(self):
    """
    Initialize HTTP session

    It must be done in a coroutine, see
    https://docs.aiohttp.org/en/stable/faq.html#why-is-creating-a-clientsession-outside-of-an-event-loop-dangerous
    """
    assert(self.session is None)
    if self.allow_session_cookies:
      cookie_jar = aiohttp.cookiejar.DummyCookieJar()
    else:
      cookie_jar = None
    self.session = await aiohttp.ClientSession(cookie_jar=cookie_jar)
