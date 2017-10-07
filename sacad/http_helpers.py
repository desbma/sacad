""" Common HTTP code. """

import asyncio
import logging
import os
import pickle

import aiohttp
import appdirs
import redo

from sacad import rate_watcher


IS_TRAVIS = os.getenv("CI") and os.getenv("TRAVIS")
HTTP_NORMAL_TIMEOUT_S = 30.1 if IS_TRAVIS else 9.1
HTTP_SHORT_TIMEOUT_S = 18.1 if IS_TRAVIS else 3.1
HTTP_MAX_ATTEMPTS = 20 if IS_TRAVIS else 3
DEFAULT_USER_AGENT = "Mozilla/5.0"


class Http:

  def __init__(self, *, allow_session_cookies, min_delay_between_accesses):
    if not allow_session_cookies:
      cookie_jar = aiohttp.helpers.DummyCookieJar()
    else:
      cookie_jar = None
    self.session = aiohttp.ClientSession(cookie_jar=cookie_jar)
    self.watcher_db_filepath = os.path.join(appdirs.user_cache_dir(appname="sacad",
                                                                   appauthor=False),
                                            "rate_watcher.sqlite")
    self.min_delay_between_accesses = min_delay_between_accesses

  def __del__(self):
    self.session.close()  # silences a warning on shutdown

  @asyncio.coroutine
  def query(self, url, *, post_data=None, headers=None, verify=True, cache=None, pre_cache_callback=None):
    """ Send a GET/POST request or get data from cache, retry if it fails, and return a tuple of cache status, response content. """
    if cache is not None:
      # try from cache first
      if post_data is not None:
        if (url, post_data) in cache:
          logging.getLogger().debug("Got data for URL '%s' %s from cache" % (url, dict(post_data)))
          return cache[(url, post_data)]
      elif url in cache:
        logging.getLogger().debug("Got data for URL '%s' from cache" % (url))
        return cache[url]

    for attempt, _ in enumerate(redo.retrier(attempts=HTTP_MAX_ATTEMPTS,
                                             sleeptime=1.5,
                                             max_sleeptime=5,
                                             sleepscale=1.25,
                                             jitter=1),
                                1):
      yield from rate_watcher.AccessRateWatcher(self.watcher_db_filepath,
                                                url,
                                                self.min_delay_between_accesses).waitAccessAsync()

      try:
        if post_data is not None:
          response = yield from self.session.post(url,
                                                  data=post_data,
                                                  headers=self._buildHeaders(headers),
                                                  timeout=HTTP_NORMAL_TIMEOUT_S)
        else:
          response = yield from self.session.get(url,
                                                 headers=self._buildHeaders(headers),
                                                 timeout=HTTP_NORMAL_TIMEOUT_S)
        content = yield from response.read()

        if cache is not None:
          if pre_cache_callback is not None:
            # process
            try:
              data = yield from pre_cache_callback(content)
            except Exception:
              data = content
          else:
            data = content

          # add to cache
          if post_data is not None:
            cache[(url, post_data)] = data
          else:
            cache[url] = data

        break  # http retry loop

      except (asyncio.TimeoutError, aiohttp.ClientError) as e:
        logging.getLogger().warning("Querying '%s' failed (attempt %u/%u): %s %s" % (url,
                                                                                     attempt,
                                                                                     HTTP_MAX_ATTEMPTS,
                                                                                     e.__class__.__qualname__,
                                                                                     e))
        if attempt == HTTP_MAX_ATTEMPTS:
          raise

    response.raise_for_status()

    return content

  @asyncio.coroutine
  def isReachable(self, url, *, headers=None, verify=True, response_headers=None, cache=None):
    """ Send a HEAD request with short timeout or get data from cache, return True if ressource has 2xx status code, False instead. """
    if (cache is not None) and (url in cache):
      # try from cache first
      logging.getLogger().debug("Got headers for URL '%s' from cache" % (url))
      resp_ok, response_headers = pickle.loads(cache[url])
      return resp_ok

    resp_ok = True
    try:
      for attempt, _ in enumerate(redo.retrier(attempts=HTTP_MAX_ATTEMPTS,
                                               sleeptime=1.5,
                                               max_sleeptime=3,
                                               sleepscale=1.25,
                                               jitter=1),
                                  1):
        yield from rate_watcher.AccessRateWatcher(self.watcher_db_filepath,
                                                  url,
                                                  self.min_delay_between_accesses).waitAccessAsync()

        try:
          response = yield from self.session.head(url,
                                                  headers=self._buildHeaders(headers),
                                                  timeout=HTTP_SHORT_TIMEOUT_S)

          break  # http retry loop

        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
          if isinstance(e, aiohttp.ClientResponseError):
            raise
          logging.getLogger().warning("Probing '%s' failed (attempt %u/%u): %s %s" % (url,
                                                                                      attempt,
                                                                                      HTTP_MAX_ATTEMPTS,
                                                                                      e.__class__.__qualname__,
                                                                                      e))
          if attempt == HTTP_MAX_ATTEMPTS:
            resp_ok = False
            break  # http retry loop

      response.raise_for_status()

      if response_headers is not None:
        response_headers.update(response.headers)

    except aiohttp.ClientResponseError as e:
      logging.getLogger().warning("Probing '%s' failed: %s %s" % (url, e.__class__.__qualname__, e))
      resp_ok = False

    if cache is not None:
      # store in cache
      cache[url] = pickle.dumps((resp_ok, response_headers))

    return resp_ok

  @asyncio.coroutine
  def fastStreamedQuery(self, url, *, headers=None, verify=True):
    """ Send a GET request with short timeout, do not retry, and return streamed response. """
    response = yield from self.session.get(url,
                                           headers=self._buildHeaders(headers),
                                           timeout=HTTP_SHORT_TIMEOUT_S)

    response.raise_for_status()

    return response

  def _buildHeaders(self, headers):
    """ Build HTTP headers dictionary. """
    if headers is None:
      headers = {}
    if "User-Agent" not in headers:
      headers["User-Agent"] = DEFAULT_USER_AGENT
    return headers


# silence third party module loggers
logging.getLogger("redo").setLevel(logging.ERROR)
