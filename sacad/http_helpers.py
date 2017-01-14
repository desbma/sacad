""" Common HTTP code. """

import http.cookiejar
import logging
import os
import pickle
import socket
import time

import appdirs
import redo
import requests

from sacad import rate_watcher


IS_TRAVIS = os.getenv("CI") and os.getenv("TRAVIS")
HTTP_NORMAL_TIMEOUT_S = 30.1 if IS_TRAVIS else 9.1
HTTP_SHORT_TIMEOUT_S = 18.1 if IS_TRAVIS else 3.1
HTTP_MAX_ATTEMPTS = 20 if IS_TRAVIS else 3
DEFAULT_USER_AGENT = "Mozilla/5.0"


class Http:

  def __init__(self, *, allow_session_cookies, min_delay_between_accesses):
    self.session = requests.Session()
    if not allow_session_cookies:
      cp = http.cookiejar.DefaultCookiePolicy(allowed_domains=[])
      self.session.cookies.set_policy(cp)
    self.watcher_db_filepath = os.path.join(appdirs.user_cache_dir(appname="sacad",
                                                                   appauthor=False),
                                            "rate_watcher.sqlite")
    self.min_delay_between_accesses = min_delay_between_accesses

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
      try:
        while True:  # rate watcher loop
          try:
            with rate_watcher.AccessRateWatcher(self.watcher_db_filepath,
                                                url,
                                                self.min_delay_between_accesses):
              if post_data is not None:
                response = self.session.post(url,
                                             data=post_data,
                                             headers=self._buildHeaders(headers),
                                             timeout=HTTP_NORMAL_TIMEOUT_S,
                                             verify=verify)
              else:
                response = self.session.get(url,
                                            headers=self._buildHeaders(headers),
                                            timeout=HTTP_NORMAL_TIMEOUT_S,
                                            verify=verify)

              if cache is not None:
                if pre_cache_callback is not None:
                  # process
                  try:
                    data = pre_cache_callback(response.content)
                  except Exception:
                    data = response.content
                else:
                  data = response.content

                # add to cache
                if post_data is not None:
                  cache[(url, post_data)] = data
                else:
                  cache[url] = data

          except rate_watcher.WaitNeeded as e:
            logging.getLogger().debug("Sleeping for %.2fms because of rate limit" % (e.wait_s * 1000))
            time.sleep(e.wait_s)

          except rate_watcher.RetryNeeded:
            pass

          else:
            break  # rate watcher loop

        break  # http retry loop

      except requests.exceptions.SSLError:
        raise

      except (socket.timeout, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        logging.getLogger().warning("Querying '%s' failed (attempt %u/%u): %s %s" % (url,
                                                                                     attempt,
                                                                                     HTTP_MAX_ATTEMPTS,
                                                                                     e.__class__.__qualname__,
                                                                                     e))
        if attempt == HTTP_MAX_ATTEMPTS:
          raise

    response.raise_for_status()

    return response.content

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
        try:
          while True:  # rate watcher loop
            try:
              with rate_watcher.AccessRateWatcher(self.watcher_db_filepath,
                                                  url,
                                                  self.min_delay_between_accesses):
                response = self.session.head(url,
                                             headers=self._buildHeaders(headers),
                                             timeout=HTTP_SHORT_TIMEOUT_S,
                                             verify=verify)

            except rate_watcher.WaitNeeded as e:
              logging.getLogger().debug("Sleeping for %.2fms because of rate limit" % (e.wait_s * 1000))
              time.sleep(e.wait_s)

            except rate_watcher.RetryNeeded:
              pass

            else:
              break  # rate watcher loop

          break  # http retry loop

        except (socket.timeout, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
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

    except requests.exceptions.HTTPError as e:
      logging.getLogger().warning("Probing '%s' failed: %s %s" % (url, e.__class__.__qualname__, e))
      resp_ok = False

    if cache is not None:
      # store in cache
      cache[url] = pickle.dumps((resp_ok, response_headers))

    return resp_ok

  def fastStreamedQuery(self, url, *, headers=None, verify=True):
    """ Send a GET request with short timeout, do not retry, and return streamed response. """
    response = self.session.get(url,
                                headers=self._buildHeaders(headers),
                                timeout=HTTP_SHORT_TIMEOUT_S,
                                verify=verify,
                                stream=True)

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
logging.getLogger("requests").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.captureWarnings(True)
