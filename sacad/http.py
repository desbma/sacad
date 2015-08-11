""" Common HTTP code. """

import contextlib
import logging
import os
import socket

import redo
import requests


IS_TRAVIS = os.getenv("CI") and os.getenv("TRAVIS")
HTTP_NORMAL_TIMEOUT_S = 30.1 if IS_TRAVIS else 9.1
HTTP_SHORT_TIMEOUT_S = 9.1 if IS_TRAVIS else 3.1
HTTP_MAX_ATTEMPTS = 10 if IS_TRAVIS else 3
USER_AGENT = "Mozilla/5.0"


def query(url, *, watcher=None, post_data=None, headers=None, verify=True):
  """ Send a GET/POST request, retry if it fails, and return response content. """
  if headers is None:
    headers = {}
  if "User-Agent" not in headers:
    headers["User-Agent"] = USER_AGENT
  for attempt, _ in enumerate(redo.retrier(attempts=HTTP_MAX_ATTEMPTS,
                                           sleeptime=1.5,
                                           max_sleeptime=5,
                                           sleepscale=1.25,
                                           jitter=1),
                              1):
    try:
      with contextlib.ExitStack() as context_manager:
        if watcher is not None:
          context_manager.enter_context(watcher)
        if post_data is not None:
          response = requests.post(url,
                                   data=post_data,
                                   headers=headers,
                                   timeout=HTTP_NORMAL_TIMEOUT_S,
                                   verify=verify)
        else:
          response = requests.get(url,
                                  headers=headers,
                                  timeout=HTTP_NORMAL_TIMEOUT_S,
                                  verify=verify)
      break
    except requests.exceptions.SSLError:
      raise
    except (socket.timeout, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
      logging.getLogger().warning("Querying '%s' failed (attempt %u/%u): %s" % (url,
                                                                                attempt,
                                                                                HTTP_MAX_ATTEMPTS,
                                                                                e.__class__.__name__))
      if attempt == HTTP_MAX_ATTEMPTS:
        raise
  response.raise_for_status()
  return response.content


def is_reachable(url, *, headers=None, verify=True):
  """ Send a HEAD request with short timeout, return True if ressource has 2xx status code, False instead. """
  if headers is None:
    headers = {}
  if "User-Agent" not in headers:
    headers["User-Agent"] = USER_AGENT
  try:
    response = requests.head(url,
                             headers=headers,
                             timeout=HTTP_SHORT_TIMEOUT_S,
                             verify=verify)
    response.raise_for_status()
  except requests.exceptions.HTTPError:
    return False
  return True


def fast_streamed_query(url, *, headers=None, verify=True):
  """ Send a GET request with short timeout, do not retry, and return streamed response. """
  if headers is None:
    headers = {}
  if "User-Agent" not in headers:
    headers["User-Agent"] = USER_AGENT
  response = requests.get(url,
                          headers=headers,
                          timeout=HTTP_SHORT_TIMEOUT_S,
                          verify=verify,
                          stream=True)
  response.raise_for_status()
  return response


# silence third party module loggers
logging.getLogger("redo").setLevel(logging.ERROR)
logging.getLogger("requests").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)
try:
  requests.packages.urllib3.disable_warnings()
except:
  pass
