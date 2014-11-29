#!/usr/bin/env python3
# -*- coding: utf-8 -*-

""" Smart Automatic Cover Art Downloader : search and download music album covers. """

__version__ = "1.1.0"
__author__ = "desbma"
__license__ = "MPL 2.0"

import abc
import argparse
import collections
import concurrent.futures
import enum
import functools
import io
import itertools
import json
import logging
import operator
import os
import pickle
import re
import shutil
import subprocess
import tempfile
import unicodedata
import urllib.parse
import xml.etree.ElementTree

import lxml.cssselect
import lxml.etree
import PIL.Image
import PIL.ImageFile
import requests

import sacad.api_watcher
import sacad.colored_logging
import sacad.mkstemp_ctx
import sacad.web_cache


USER_AGENT = "Mozilla/5.0"
MAX_THUMBNAIL_SIZE = 256


CoverSourceQuality = enum.Enum("CoverSourceQuality", ("LOW", "NORMAL", "REFERENCE"))
CoverImageFormat = enum.Enum("CoverImageFormat", ("JPEG", "PNG"))
SUPPORTED_IMG_FORMATS = {"jpg": CoverImageFormat.JPEG,
                         "jpeg": CoverImageFormat.JPEG,
                         "png": CoverImageFormat.PNG}

HAS_OPTIPNG = shutil.which("optipng") is not None
HAS_JPEGOPTIM = shutil.which("jpegoptim") is not None


class CoverSourceResult:

  """ Cover image returned by a source, candidate to be downloaded. """

  MAX_FILE_METADATA_PEEK_SIZE = 2 ** 15
  IMG_SIG_SIZE = 16

  def __init__(self, url, size, format, *, thumbnail_url, source_quality, rank=None, check_metadata=False):
    """
    Args:
      url: Cover image file URL
      size: Cover size as a (with, height) tuple
      format: Cover image format as a CoverImageFormat enum, or None if unknown
      thumbnail_url: Cover thumbnail image file URL, or None if not available
      source_quality: Quality of the cover's source as a CoverSourceQuality enum value
      rank: Integer ranking of the cover in the other results from the same source, or None if not available
      check_metadata: If True, hint that the format and/or size parameters are not reliable and must be double checked
    """
    self.url = url
    self.size = size
    self.format = format
    self.thumbnail_url = thumbnail_url
    self.thumbnail_sig = None
    self.source_quality = source_quality
    self.rank = rank
    self.check_metadata = check_metadata
    self.is_similar_to_reference = False
    self.is_only_reference = False
    if not hasattr(__class__, "image_cache"):
      cache_filename = "sacad-cache.sqlite"
      __class__.image_cache = web_cache.ThreadedWebCache("cover_image_data",
                                                         db_filename=cache_filename,
                                                         caching_strategy=web_cache.CachingStrategy.LRU,
                                                         expiration=60 * 60 * 24 * 365)  # 1 year
      __class__.metadata_cache = web_cache.ThreadedWebCache("cover_metadata",
                                                            db_filename=cache_filename,
                                                            caching_strategy=web_cache.CachingStrategy.LRU,
                                                            expiration=60 * 60 * 24 * 365)  # 1 year
      for cache, cache_name in zip((__class__.image_cache, __class__.metadata_cache),
                                   ("cover_image_data", "cover_metadata")):
        purged_count = cache.purge()
        logging.getLogger().debug("%u obsolete entries have been removed from cache '%s'" % (purged_count, cache_name))
        row_count = len(cache)
        logging.getLogger().debug("Cache '%s' contains %u entries" % (cache_name, row_count))

  def __str__(self):
    return "%s '%s'" % (self.__class__.__name__, self.url)

  def get(self, target_format, target_size, size_tolerance_prct, out_filepath):
    """ Download cover and process it. """
    if self.source_quality.value <= CoverSourceQuality.LOW.value:
      logging.getLogger().warning("Cover is from a potentially unreliable source and may be unrelated to the search")
    if self.url in __class__.image_cache:
      # cache hit
      logging.getLogger().info("Got data for URL '%s' from cache" % (self.url))
      image_data = __class__.image_cache[self.url]
    else:
      # download
      logging.getLogger().info("Downloading cover '%s'..." % (self.url))
      response = requests.get(self.url, headers={"User-Agent": USER_AGENT}, timeout=10, verify=False)
      response.raise_for_status()
      image_data = response.content

      # crunch image
      image_data = __class__.crunch(image_data, self.format)

      # save it to cache
      __class__.image_cache[self.url] = image_data

    need_format_change = (self.format != target_format)
    need_size_change = ((max(self.size) > target_size) and
                        (abs(max(self.size) - target_size) >
                         target_size * size_tolerance_prct / 100))
    if need_format_change or need_size_change:
      # convert
      image_data = self.convert(image_data,
                                target_format if need_format_change else None,
                                target_size if need_size_change else None)

      # crunch image again
      image_data = __class__.crunch(image_data, target_format)

    # write it
    with open(out_filepath, "wb") as file:
      file.write(image_data)

  def convert(self, image_data, new_format, new_size):
    """
    Convert image, and return the processed data, or original data if something went wrong.

    Convert image binary data to a target format and/or size (None if no conversion needed).
    Return the binary data of the output image, or None if conversion failed

    """
    logging.getLogger().info("Converting to%s%s..." % ((" %ux%u" % (new_size, new_size)) if new_size is not None else "",
                                                       (" %s" % (new_format.name.upper())) if new_format is not None else ""))
    in_bytes = io.BytesIO(image_data)
    img = PIL.Image.open(in_bytes)
    out_bytes = io.BytesIO()
    if new_size is not None:
      img = img.resize((new_size, new_size))
    if new_format is not None:
      target_format = new_format
    else:
      target_format = self.format
    img.save(out_bytes, format=target_format.name, quality=90, optimize=True)
    return out_bytes.getvalue()

  def updateImageMetadata(self):
    """ Partially download an image file to get its real metadata, or get it from cache. """
    if self.url in __class__.metadata_cache:
      # cache hit
      logging.getLogger().debug("Got metadata for URL '%s' from cache" % (self.url))
      format, width, height = pickle.loads(__class__.metadata_cache[self.url])
    else:
      # download
      logging.getLogger().debug("Downloading file header for URL '%s'..." % (self.url))
      try:
        response = requests.get(self.url,
                                headers={"User-Agent": USER_AGENT},
                                timeout=3,
                                verify=False,
                                stream=True)
        response.raise_for_status()
        metadata = None
        img_data = bytearray()
        for new_img_data in response.iter_content(chunk_size=2 ** 12):
          img_data.extend(new_img_data)
          metadata = __class__.getImageMetadata(img_data)
          if metadata is not None:
            break
        if metadata is None:
          logging.getLogger().debug("Unable to get file metadata from file header for URL '%s', skipping this result" % (self.url))
          return self  # for use with concurrent.futures
      except requests.exceptions.RequestException:
        logging.getLogger().debug("Unable to get file metadata for URL '%s', falling back to API data" % (self.url))
        self.check_metadata = False
        return self  # for use with concurrent.futures

      # hoorah !
      format, width, height = metadata

      # save it to cache
      __class__.metadata_cache[self.url] = pickle.dumps((format, width, height))

    self.check_metadata = False
    self.format = format
    self.size = (width, height)

    return self  # for use with concurrent.futures

  def updateSignature(self):
    """ Calculate a cover's "signature" using its thumbnail url. """
    assert(self.thumbnail_sig is None)
    if self.thumbnail_url is None:
      logging.getLogger().warning("No thumbnail available for %s" % (self))
      return
    if self.thumbnail_url in __class__.image_cache:
      # cache hit
      logging.getLogger().debug("Got data for URL '%s' from cache" % (self.thumbnail_url))
      image_data = __class__.image_cache[self.thumbnail_url]
    else:
      # download
      logging.getLogger().info("Downloading cover thumbnail '%s'..." % (self.thumbnail_url))
      try:
        response = requests.get(self.thumbnail_url, headers={"User-Agent": USER_AGENT}, timeout=10, verify=False)
        response.raise_for_status()
        image_data = response.content
      except requests.exceptions.RequestException:
        logging.getLogger().warning("Download of '%s' failed" % (self.thumbnail_url))
        return self  # for use with concurrent.futures
      else:
        # crunch image
        image_data = __class__.crunch(image_data, CoverImageFormat.JPEG, silent=True)  # assume thumbnails are always JPG
        # save it to cache
        __class__.image_cache[self.thumbnail_url] = image_data

    # compute sig
    logging.getLogger().debug("Computing signature of %s..." % (self))
    self.thumbnail_sig = __class__.computeImgSignature(image_data)

    return self  # for use with concurrent.futures

  @staticmethod
  def compare(first, second, *, target_size, size_tolerance_prct):
    """
    Compare cover relevance/quality.

    Return -1 if first is a worst match than second, 1 otherwise, or 0 if cover can't be discriminated.

    This code is responsible for comparing two cover results to identify the best one, and is used to sort all results.
    It is probably the most important piece of code of this tool.
    The following factors are used in order:
      1. Prefer approximately square covers
      2. Prefer covers of "reference" source quality
      3. Prefer covers similar to the reference cover
      4. Prefer size above target size
      5. Prefer covers of reliable source
      6. Prefer best ranked cover
    If all previous factors do not allow sorting of two results (very unlikely):
      7. Prefer covers having the target size
      8. Prefer PNG covers
      9. Prefer exactly square covers

    We don't overload the __lt__ operator because we need to pass the target_size parameter.

    """
    # prefer square covers #1
    delta_ratio1 = abs(first.size[0] / first.size[1] - 1)
    delta_ratio2 = abs(second.size[0] / second.size[1] - 1)
    if abs(delta_ratio1 - delta_ratio2) > 0.04:
      return -1 if (delta_ratio1 > delta_ratio2) else 1

    # prefer reference
    r1 = first.source_quality is CoverSourceQuality.REFERENCE
    r2 = second.source_quality is CoverSourceQuality.REFERENCE
    if r1 and (not r2):
      return 1
    if (not r1) and r2:
      return -1

    # prefer similar to reference
    sr1 = first.is_similar_to_reference
    sr2 = second.is_similar_to_reference
    if sr1 and (not sr2):
      return 1
    if (not sr1) and sr2:
      return -1

    # prefer size above preferred
    delta_side1 = ((first.size[0] + first.size[1]) / 2) - target_size
    delta_side2 = ((second.size[0] + second.size[1]) / 2) - target_size
    if ((delta_side1 < -(size_tolerance_prct * target_size / 100)) or
            (delta_side2 < -(size_tolerance_prct * target_size / 100))):
      return -1 if (delta_side1 < delta_side2) else 1

    # prefer covers of reliable source
    qs1 = first.source_quality.value
    qs2 = second.source_quality.value
    if qs1 != qs2:
      return qs1 < qs2

    # prefer best ranked
    if ((first.rank is not None) and
            (second.rank is not None) and
            (first.__class__ is second.__class__) and
            (first.rank != second.rank)):
      return -1 if (first.rank > second.rank) else 1

    # prefer the preferred size
    if abs(delta_side1) != abs(delta_side2):
      return -1 if (abs(delta_side1) > abs(delta_side2)) else 1

    # prefer png
    if first.format != second.format:
      return -1 if (second.format is CoverImageFormat.PNG) else 1

    # prefer square covers #2
    if (delta_ratio1 != delta_ratio2):
      return -1 if (delta_ratio1 > delta_ratio2) else 1

    # fuck, they are the same!
    return 0

  @staticmethod
  def crunch(image_data, format, silent=False):
    """ Crunch image data, and return the processed data, or orignal data if operation failed. """
    if (((format is CoverImageFormat.PNG) and (not HAS_OPTIPNG)) or
            ((format is CoverImageFormat.JPEG) and (not HAS_JPEGOPTIM))):
      return image_data
    with mkstemp_ctx.mkstemp(suffix=".%s" % (format.name.lower())) as tmp_out_filepath:
      if not silent:
        logging.getLogger().info("Crunching %s image..." % (format.name.upper()))
      with open(tmp_out_filepath, "wb") as tmp_out_file:
        tmp_out_file.write(image_data)
      size_before = len(image_data)
      if format is CoverImageFormat.PNG:
        cmd = ["optipng", "-quiet", "-o5"]
      elif format is CoverImageFormat.JPEG:
        cmd = ["jpegoptim", "-q", "--strip-all"]
      cmd.append(tmp_out_filepath)
      try:
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
      except subprocess.CalledProcessError:
        if not silent:
          logging.getLogger().warning("Crunching image failed")
        return image_data
      with open(tmp_out_filepath, "rb") as tmp_out_file:
        crunched_image_data = tmp_out_file.read()
      size_after = len(crunched_image_data)
      pct_saved = 100 * (size_before - size_after) / size_before
      if not silent:
        logging.getLogger().debug("Crunching image saved %.2f%% filesize" % (pct_saved))
    return crunched_image_data

  @staticmethod
  def getImageMetadata(img_data):
    """ Identify an image format and size from its first bytes. """
    img_stream = io.BytesIO(img_data)
    try:
      img = PIL.Image.open(img_stream)
    except IOError:
      return None
    format = img.format.lower()
    format = SUPPORTED_IMG_FORMATS.get(format, None)
    width, height = img.size
    return format, width, height

  @staticmethod
  def preProcessForComparison(results, target_size, size_tolerance_prct):
    """ Process results to prepare them for future comparison and sorting. """
    # find reference (=image most likely to match target cover ignoring factors like size and format)
    reference = None
    for result in results:
      if result.source_quality is CoverSourceQuality.REFERENCE:
        if ((reference is None) or
            (CoverSourceResult.compare(result,
                                       reference,
                                       target_size=target_size,
                                       size_tolerance_prct=size_tolerance_prct) > 0)):
          reference = result

    # remove results that are only refs
    results = list(itertools.filterfalse(operator.attrgetter("is_only_reference"), results))

    if reference is not None:
      logging.getLogger().info("Reference is: %s" % (reference))
      reference.is_similar_to_reference = True

      # calculate sigs using thread pool
      with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = []
        for result in results:
          futures.append(executor.submit(CoverSourceResult.updateSignature, result))
        if reference.is_only_reference:
          assert(reference not in results)
          futures.append(executor.submit(CoverSourceResult.updateSignature, reference))
        concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_EXCEPTION)
        # raise first exception in future if any
        for future in futures:
          try:
            e = future.exception(timeout=0)
          except concurrent.futures.TimeoutError:
            continue
          if e is not None:
            # try to stop all pending futures
            for future_to_cancel in futures:
              future_to_cancel.cancel()
            raise e
        results = list(future.result() for future in futures if not future.result().is_only_reference)

      # compare other results to reference
      for result in results:
        if ((result is not reference) and
                (result.thumbnail_sig is not None) and
                (reference.thumbnail_sig is not None)):
          result.is_similar_to_reference = __class__.areImageSigsSimilar(result.thumbnail_sig,
                                                                         reference.thumbnail_sig)
          if result.is_similar_to_reference:
            logging.getLogger().debug("%s is similar to reference" % (result))
          else:
            logging.getLogger().debug("%s is NOT similar to reference" % (result))
    else:
      logging.getLogger().warning("No reference result found")

    return results

  @staticmethod
  def computeImgSignature(image_data):
    """
    Calculate an image signature.

    The "signature" is in fact a IMG_SIG_SIZE x IMG_SIG_SIZE matrix of 24 bits RGB pixels.
    It is obtained through simple downsizing.

    """
    parser = PIL.ImageFile.Parser()
    parser.feed(image_data)
    img = parser.close()
    target_size = (__class__.IMG_SIG_SIZE, __class__.IMG_SIG_SIZE)
    img.thumbnail(target_size, PIL.Image.ANTIALIAS)
    if img.size != target_size:
      logging.getLogger().debug("Non square thumbnail after resize to %ux%u, unable to compute signature" % target_size)
      return None
    img = img.convert(mode="RGB")
    return tuple(img.getdata())

  @staticmethod
  def areImageSigsSimilar(sig1, sig2):
    """
    Compare 2 image "signatures" and return True if they seem to come from a similar image, False otherwise.

    This is determined by first calculating the average square distance by pixel between the two image signatures (wich
    are in fact just a very downsized image), and then comparing the value with an empirically deduced threshold.
    Stupid simple, but it seems to work pretty well.

    """
    delta = 0
    for x in range(__class__.IMG_SIG_SIZE):
      for y in range(__class__.IMG_SIG_SIZE):
        p1 = sig1[x * __class__.IMG_SIG_SIZE + y]
        p2 = sig2[x * __class__.IMG_SIG_SIZE + y]
        assert(len(p1) == len(p2) == 3)
        for c1, c2 in zip(p1, p2):
          delta += ((c1 - c2) ** 2) / 3
    delta = delta / (__class__.IMG_SIG_SIZE * __class__.IMG_SIG_SIZE)
    return delta < 3000


class LastFmCoverSourceResult(CoverSourceResult):

  def __init__(self, *args, **kwargs):
    super().__init__(*args, source_quality=CoverSourceQuality.REFERENCE, **kwargs)


class GoogleImagesCoverSourceResult(CoverSourceResult):

  def __init__(self, *args, **kwargs):
    super().__init__(*args, source_quality=CoverSourceQuality.LOW, **kwargs)


class CoverParadiseCoverSourceResult(CoverSourceResult):

  def __init__(self, *args, **kwargs):
    super().__init__(*args, source_quality=CoverSourceQuality.NORMAL, **kwargs)


class AmazonCoverSourceResult(CoverSourceResult):

  def __init__(self, *args, **kwargs):
    super().__init__(*args, source_quality=CoverSourceQuality.NORMAL, **kwargs)


class CoverSource(metaclass=abc.ABCMeta):

  """ Base class for all cover sources. """

  def __init__(self, target_size, size_tolerance_prct, prefer_https, min_delay_between_accesses=2 / 3):
    self.target_size = target_size
    self.size_tolerance_prct = size_tolerance_prct
    self.prefer_https = prefer_https
    tmp_dir = "/var/tmp" if os.path.isdir("/var/tmp") else tempfile.gettempdir()
    db_filepath = os.path.join(tmp_dir, "api_watcher_%s.sqlite" % (self.__class__.__name__.lower()))
    self.api_watcher = api_watcher.ApiAccessRateWatcher(logging.getLogger(),
                                                        db_filepath=db_filepath,
                                                        min_delay_between_accesses=min_delay_between_accesses)
    if not hasattr(__class__, "api_cache"):
      db_filename = "sacad-cache.sqlite"
      cache_name = "cover_source_api_data"
      __class__.api_cache = web_cache.WebCache(cache_name,
                                               db_filename=db_filename,
                                               caching_strategy=web_cache.CachingStrategy.FIFO,
                                               expiration=60 * 60 * 24 * 90,  # 3 month
                                               compression=web_cache.Compression.DEFLATE)
      logging.getLogger().debug("Total size of file '%s': %s" % (db_filename,
                                                                 __class__.api_cache.getDatabaseFileSize()))
      purged_count = __class__.api_cache.purge()
      logging.getLogger().debug("%u obsolete entries have been removed from cache '%s'" % (purged_count, cache_name))
      row_count = len(__class__.api_cache)
      logging.getLogger().debug("Cache '%s' contains %u entries" % (cache_name, row_count))

  def search(self, album, artist):
    """ Search for a given album/artist and return an iterable of CoverSourceResult. """
    logging.getLogger().debug("Searching with source '%s'..." % (self.__class__.__name__))
    url_data = self.getSearchUrl(album, artist)
    if isinstance(url_data, tuple):
      url, post_data = url_data
    else:
      url = url_data
      post_data = None
    try:
      cache_hit, api_data = self.fetchResults(url, post_data)
      results = self.parseResults(api_data)
      if not cache_hit:
        # add cache entry only when parsing is successful
        if post_data is not None:
          CoverSource.api_cache[(url, post_data)] = api_data
        else:
          CoverSource.api_cache[url] = api_data
    except Exception as e:
      #raise
      logging.getLogger().warning("Search with source '%s' failed: %s" % (self.__class__.__name__, e))
      return ()

    # get metadata using thread pool
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
      futures = []
      for result in filter(operator.attrgetter("check_metadata"), results):
        futures.append(executor.submit(CoverSourceResult.updateImageMetadata, result))
      results = list(itertools.filterfalse(operator.attrgetter("check_metadata"), results))
      concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_EXCEPTION)
      # raise first exception in future if any
      for future in futures:
        try:
          e = future.exception(timeout=0)
        except concurrent.futures.TimeoutError:
          continue
        if e is not None:
          # try to stop all pending futures
          for future_to_cancel in futures:
            future_to_cancel.cancel()
          raise e
      results.extend(future.result() for future in futures)

    # filter
    results_excluded_count = 0
    reference_only_count = 0
    results_kept = []
    for result in results:
      if ((result.size[0] + (self.size_tolerance_prct * self.target_size / 100) < self.target_size) or  # skip too small images
              (result.size[1] + (self.size_tolerance_prct * self.target_size / 100) < self.target_size) or
              (result.format not in CoverImageFormat) or  # unknown format
              result.check_metadata):  # if still true, it means we failed to grab metadata, so exclude it
        if result.source_quality is CoverSourceQuality.REFERENCE:
          # we keep this result just for the reference, it will be excluded from the results
          result.is_only_reference = True
          results_kept.append(result)
          reference_only_count += 1
        else:
          results_excluded_count += 1
      else:
        results_kept.append(result)
    result_kept_count = len(results_kept) - reference_only_count

    # log
    logging.getLogger().info("Got %u relevant (%u excluded) results from source '%s'" % (result_kept_count,
                                                                                         results_excluded_count + reference_only_count,
                                                                                         self.__class__.__name__))
    for result in itertools.filterfalse(operator.attrgetter("is_only_reference"), results_kept):
      logging.getLogger().debug("\t- %s%s %4dx%4d %s" % (("(%02d) " % (result.rank)) if result.rank is not None else "",
                                                         result.format.name,
                                                         result.size[0],
                                                         result.size[1],
                                                         result.url))
    return results_kept

  def fetchResults(self, url, post_data=None):
    """ Get search result of an URL from cache or HTTP. """
    cache_hit = False
    if post_data is not None:
      if (url, post_data) in __class__.api_cache:
        logging.getLogger().debug("Got data for URL '%s' %s from cache" % (url, dict(post_data)))
        data = __class__.api_cache[(url, post_data)]
        cache_hit = True
    elif url in __class__.api_cache:
      logging.getLogger().debug("Got data for URL '%s' from cache" % (url))
      data = __class__.api_cache[url]
      cache_hit = True

    if not cache_hit:
      if post_data is not None:
        logging.getLogger().debug("Querying URL '%s' %s..." % (url, dict(post_data)))
      else:
        logging.getLogger().debug("Querying URL '%s'..." % (url))
      headers = {"User-Agent": USER_AGENT}
      self.updateHttpHeaders(headers)
      with self.api_watcher:
        if post_data is not None:
          response = requests.post(url, data=post_data, headers=headers, timeout=5, verify=False)
        else:
          response = requests.get(url, headers=headers, timeout=5, verify=False)
      response.raise_for_status()
      data = response.content
      # add cache entry only when parsing is successful
    return cache_hit, data

  @staticmethod
  def assembleUrl(base_url, params):
    """ Build an URL from URL base and parameters. """
    return "%s?%s" % (base_url, urllib.parse.urlencode(params))

  @staticmethod
  def unaccentuate(s):
    """ Replace accentuated chars in string by their non accentuated equivalent. """
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

  @abc.abstractmethod
  def getSearchUrl(self, album, artist):
    """
    Build a search results URL from an album and/or artist name.

    If the URL must be accessed with an HTTP GET request, return the URL as a string.
    If the URL must be accessed with an HTTP POST request, return a tuple with:
    - the URL as a string
    - the post parameters as a collections.OrderedDict

    """
    pass

  @abc.abstractmethod
  def updateHttpHeaders(self, headers):
    """ Add API specific HTTP headers. """
    pass

  @abc.abstractmethod
  def parseResults(self, api_data):
    """ Parse API data and return an iterable of results. """
    pass


class GoogleImagesWebScrapeCoverSource(CoverSource):

  """
  Cover source that scrapes Google Images search result pages.

  Google Image Search JSON API is not used because it is deprecated and Google
  is very agressively rate limiting its access.
  """

  BASE_URL = "http://www.google.com/images"
  BASE_URL_HTTPS = "https://www.google.com/images"

  def getSearchUrl(self, album, artist):
    """ See CoverSource.getSearchUrl. """
    # build request url
    if self.prefer_https:
      base_url = __class__.BASE_URL_HTTPS
    else:
      base_url = __class__.BASE_URL

    params = collections.OrderedDict()
    params["gbv"] = "2"
    params["q"] = "\"%s\" \"%s\" front cover" % (artist.lower(), album.lower())
    if abs(self.target_size - 500) < 300:
      params["tbs"] = "isz:m"
    elif self.target_size > 800:
      params["tbs"] = "isz:l"

    return __class__.assembleUrl(base_url, params)

  def updateHttpHeaders(self, headers):
    """ See CoverSource.updateHttpHeaders. """
    headers["User-Agent"] = "Mozilla/5.0 Firefox/25.0"

  def parseResults(self, api_data):
    """ See CoverSource.parseResults. """
    results = []

    # parse HTML and get results
    parser = lxml.etree.HTMLParser()
    html = lxml.etree.XML(api_data.decode("latin-1"), parser)
    results_selector = lxml.cssselect.CSSSelector("#search #rg_s .rg_di")
    for rank, result in enumerate(results_selector(html), 1):
      # extract url
      google_url = result.find("a").get("href")
      query = urllib.parse.urlsplit(google_url).query
      query = urllib.parse.parse_qs(query)
      img_url = query["imgurl"][0]
      # extract format
      metadata_div = result.find("div")
      metadata_json = lxml.etree.tostring(metadata_div, encoding="unicode", method="text")
      metadata_json = json.loads(metadata_json)
      check_metadata = False
      format = metadata_json["ity"].lower()
      try:
        format = SUPPORTED_IMG_FORMATS[format]
      except KeyError:
        # format could not be identified or is unknown
        format = None
        check_metadata = True
      # extract size
      size = tuple(map(int, (query["w"][0], query["h"][0])))
      assert(size[0] == metadata_json["ow"])
      assert(size[1] == metadata_json["oh"])
      # extract thumbnail url
      thumbnail_url = metadata_json["tu"]
      # result
      results.append(GoogleImagesCoverSourceResult(img_url,
                                                   size,
                                                   format,
                                                   thumbnail_url=thumbnail_url,
                                                   rank=rank,
                                                   check_metadata=check_metadata))

    return results


class LastFmCoverSource(CoverSource):

  """
  Cover source using the official LastFM API.

  http://www.lastfm.fr/api/show?service=290
  """

  BASE_URL = "http://ws.audioscrobbler.com/2.0/"
  BASE_URL_HTTPS = "https://ws.audioscrobbler.com/2.0/"
  API_KEY = "2410a53db5c7490d0f50c100a020f359"

  SIZES = {"small": (34, 34),
           "medium": (64, 64),
           "large": (174, 174),
           "extralarge": (300, 300),
           "mega": (600, 600)}  # this is actually between 600 and 900, sometimes even more (ie 1200)

  def getSearchUrl(self, album, artist):
    """ See CoverSource.getSearchUrl. """
    # build request url
    if self.prefer_https:
      base_url = __class__.BASE_URL_HTTPS
    else:
      base_url = __class__.BASE_URL

    params = collections.OrderedDict()
    params["method"] = "album.getinfo"
    params["api_key"] = __class__.API_KEY
    params["album"] = album.lower()
    params["artist"] = artist.lower()

    return __class__.assembleUrl(base_url, params)

  def updateHttpHeaders(self, headers):
    """ See CoverSource.updateHttpHeaders. """
    pass

  def parseResults(self, api_data):
    """ See CoverSource.parseResults. """
    results = []

    # get xml results list
    xml_text = api_data.decode("utf-8")
    xml_root = xml.etree.ElementTree.fromstring(xml_text)
    status = xml_root.get("status")
    if status != "ok":
      raise Exception("Unexpected Last.fm response status: %s" % (status))
    img_elements = xml_root.findall("album/image")

    # build results from xml
    thumbnail_url = None
    thumbnail_size = None
    for img_element in img_elements:
      img_url = img_element.text
      if not img_url:
        # last.fm returns empty image tag for size it does not have
        continue
      lfm_size = img_element.get("size")
      check_metadata = (lfm_size == "mega")
      size = __class__.SIZES[lfm_size]
      if (size[0] <= MAX_THUMBNAIL_SIZE) and ((thumbnail_size is None) or (size[0] < thumbnail_size)):
        thumbnail_url = img_url
        thumbnail_size = size[0]
      format = os.path.splitext(img_url)[1][1:].lower()
      format = SUPPORTED_IMG_FORMATS[format]
      results.append(LastFmCoverSourceResult(img_url,
                                             size,
                                             format,
                                             thumbnail_url=thumbnail_url,
                                             check_metadata=check_metadata))

    return results


class CoverParadiseCoverSource(CoverSource):

  """ Cover source that scrapes the ecover.to site. """

  BASE_URL = "http://ecover.to/"

  def getSearchUrl(self, album, artist):
    """ See CoverSource.getSearchUrl. """
    url = "%sLookup.html" % (__class__.BASE_URL)
    post_params = collections.OrderedDict()
    post_params["B1"] = "Search!"
    post_params["Page"] = "0"
    post_params["SearchString"] = "%s %s" % (artist.lower(), album.lower())
    post_params["Sektion"] = "2"
    return url, post_params

  def updateHttpHeaders(self, headers):
    """ See CoverSource.updateHttpHeaders. """
    pass

  def parseResults(self, api_data):
    """ See CoverSource.parseResults. """
    results = []

    # parse page
    parser = lxml.etree.HTMLParser()
    html = lxml.etree.XML(api_data.decode("latin-1"), parser)
    results_selector = lxml.cssselect.CSSSelector("#EntryForm div.ThumbDetailsX")
    subresults_selector = lxml.cssselect.CSSSelector("#Formel2 table.Table_SimpleSearchResult tr")
    type_selector = lxml.cssselect.CSSSelector("span.Label")
    info_selector = lxml.cssselect.CSSSelector("div.Info")
    size_regex = re.compile("([0-9.]+)x([0-9.]+)px")
    size_regex2 = re.compile("^([0-9.]+) x ([0-9.]+) px")
    divs = results_selector(html)

    if not divs:
      # intermediate page
      subresults_nodes = subresults_selector(html)
      rank = 1
      for subresults_node in subresults_nodes:
        td_it = subresults_node.iterfind("td")
        td1 = next(td_it)
        try:
          td2 = next(td_it)
        except StopIteration:
          continue
        td2_txt = lxml.etree.tostring(td2, encoding="unicode", method="text")
        # skip non front covers
        cover_types = frozenset(map(str.strip, td2_txt.split("Elements:")[-1].split("Dimensions:", 1)[0].split("|")))
        if "Front" not in cover_types:
          continue
        # get resolution
        res_txt = td2_txt.split("Dimensions:")[-1].split("Filesize:", 1)[0].strip()
        re_match = size_regex2.search(res_txt)
        size = tuple(map(int, re_match.group(1, 2)))
        # get thumbnail url
        link = td1.find("a")
        if link is None:
          # no thumbnail, likely low quality result
          continue
        thumbnail_url = link.find("img").get("src")
        # deduce img url without downloading subpage
        cover_id = int(thumbnail_url.rsplit(".", 1)[0].rsplit("/", 1)[1])
        cover_name = link.get("href").rsplit(".", 1)[0].rsplit("/", 1)[1]
        img_url = "%sDownload/%u/%s-Front.JPG" % (__class__.BASE_URL, cover_id, cover_name)
        # assume format is always jpg
        format = CoverImageFormat.JPEG
        # add result
        results.append(CoverParadiseCoverSourceResult(img_url,
                                                      size,
                                                      format,
                                                      thumbnail_url=thumbnail_url,
                                                      rank=rank))
        rank += 1
    else:
      # direct result page
      for div in divs:
        # skip non front covers
        cover_type = type_selector(div)[0].text.strip()
        if cover_type != "Front":
          continue
        # get resolution
        info_txt = info_selector(div)[0].text.strip()
        re_match = size_regex.search(info_txt)
        size = tuple(map(int,
                         map("".join,
                             map(operator.methodcaller("split", "."),
                                 re_match.group(1, 2)))))
        # get img url
        link = div.find("a")
        img_url = link.get("href")
        img_url = "%s%s" % (__class__.BASE_URL.rstrip("/"), img_url)
        # assume format is always jpg
        format = CoverImageFormat.JPEG
        # get thumbnail url
        thumbnail_url = link.find("img").get("src")
        # add result
        results.append(CoverParadiseCoverSourceResult(img_url,
                                                      size,
                                                      format,
                                                      thumbnail_url=thumbnail_url))

    return results


class AmazonCoverSource(CoverSource):

  """ Cover source returning Amazon.com album images. """

  BASE_URL = "http://www.amazon.com/gp/search"

  def getSearchUrl(self, album, artist):
    """ See CoverSource.getSearchUrl. """
    params = collections.OrderedDict()
    params["search-alias"] = "popular"
    params["field-artist"] = __class__.unaccentuate(artist.lower())
    params["field-title"] = __class__.unaccentuate(album.lower())
    params["sort"] = "relevancerank"
    return __class__.assembleUrl(__class__.BASE_URL, params)

  def updateHttpHeaders(self, headers):
    """ See CoverSource.updateHttpHeaders. """
    pass

  def parseResults(self, api_data):
    """ See CoverSource.parseResults. """
    results = []

    # parse page
    parser = lxml.etree.HTMLParser()
    html = lxml.etree.XML(api_data.decode("utf-8"), parser)
    results_selector = lxml.cssselect.CSSSelector("#resultsCol li.s-result-item")
    img_selector = lxml.cssselect.CSSSelector("img.s-access-image")
    product_link_selector = lxml.cssselect.CSSSelector("a.s-access-detail-page")
    product_page_img_selector = lxml.cssselect.CSSSelector("img#landingImage")
    result_divs = results_selector(html)
    for rank, result_div in enumerate(result_divs, 1):
      try:
        img_node = img_selector(result_div)[0]
      except IndexError:
        # no image for that product
        continue
      # get thumbnail & full image url
      thumbnail_url = img_node.get("src")
      url_parts = thumbnail_url.rsplit(".", 2)
      img_url = ".".join((url_parts[0], url_parts[2]))
      # assume size is fixed
      size = (500, 500)
      check_metadata = True
      # try to get higher res image...
      if ((self.target_size > size[0]) and  # ...only if needed
              (rank < 3)):  # and only for first 3 results because this is time consuming (1 GET request per result)
        product_url = product_link_selector(result_div)[0].get("href")
        product_url = urllib.parse.urlsplit(product_url)
        product_url_query = urllib.parse.parse_qsl(product_url.query)
        product_url_query = collections.OrderedDict(product_url_query)
        del product_url_query["qid"]  # remove timestamp from url to improve future cache hit rate
        product_url_query = urllib.parse.urlencode(product_url_query)
        product_url = urllib.parse.urlunsplit(product_url[:3] + (product_url_query,) + product_url[4:])
        cache_hit, product_page_data = self.fetchResults(product_url)
        product_page_html = lxml.etree.XML(product_page_data.decode("latin-1"), parser)
        try:
          img_node = product_page_img_selector(product_page_html)[0]
        except IndexError:
          # unable to get better image
          pass
        else:
          better_img_url = img_node.get("data-old-hires")
          # img_node.get("data-a-dynamic-image") contains json with image urls too, but they are not larger than
          # previous 500px image and are often covered by autorip badges (can be removed by cleaning url though)
          if better_img_url:
            img_url = better_img_url
            size_url_hint = img_url.rsplit(".", 2)[1].strip("_")
            assert(size_url_hint.startswith("SL"))
            size_url_hint = int(size_url_hint[2:])
            size = (size_url_hint, size_url_hint)
            check_metadata = False
          if not cache_hit:
            # add cache entry only when parsing is successful
            CoverSource.api_cache[product_url] = product_page_data
      # assume format is always jpg
      format = CoverImageFormat.JPEG
      # add result
      results.append(AmazonCoverSourceResult(img_url,
                                             size,
                                             format,
                                             thumbnail_url=thumbnail_url,
                                             rank=rank,
                                             check_metadata=check_metadata))

    return results


def main(album, artist, format, size, size_tolerance_prct, no_lq_sources, prefer_https, out_filepath):
  # display warning if optipng or jpegoptim are missing
  if not HAS_OPTIPNG:
    logging.getLogger().warning("optipng could not be found, PNG crunching will be disabled")
  if not HAS_JPEGOPTIM:
    logging.getLogger().warning("jpegoptim could not be found, JPEG crunching will be disabled")

  # register sources
  sources = [LastFmCoverSource(size, size_tolerance_prct, prefer_https),
             CoverParadiseCoverSource(size, size_tolerance_prct, prefer_https),
             AmazonCoverSource(size, size_tolerance_prct, prefer_https)]
  if not no_lq_sources:
    sources.append(GoogleImagesWebScrapeCoverSource(size, size_tolerance_prct, prefer_https))

  # search
  results = []
  for source in sources:
    results.extend(source.search(album, artist))

  # sort results
  results = CoverSourceResult.preProcessForComparison(results, size, size_tolerance_prct)
  results.sort(reverse=True,
               key=functools.cmp_to_key(functools.partial(CoverSourceResult.compare,
                                                          target_size=size,
                                                          size_tolerance_prct=size_tolerance_prct)))
  if not results:
    logging.getLogger().info("No results")

  # download
  for result in results:
    try:
      result.get(format, size, size_tolerance_prct, out_filepath)
    except Exception as e:
      logging.getLogger().warning("Download of %s failed: %s" % (result, e))
      continue
    else:
      break


def cl_main():
  # parse args
  arg_parser = argparse.ArgumentParser(description="SACAD v%s. Search and download an album cover." % (__version__),
                                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
  arg_parser.add_argument("artist",
                          help="Artist to search for")
  arg_parser.add_argument("album",
                          help="Album to search for")
  arg_parser.add_argument("size",
                          type=int,
                          help="Target image size")
  arg_parser.add_argument("out_filepath",
                          help="Output image file")
  arg_parser.add_argument("-t",
                          "--size-tolerance",
                          type=int,
                          default=25,
                          dest="size_tolerance_prct",
                          help="""Tolerate this percentage of size difference with the target size.
                                  Note that covers with size above or close to the target size will still be preferred
                                  if available""")
  arg_parser.add_argument("-d",
                          "--disable-low-quality-sources",
                          action="store_true",
                          default=False,
                          dest="no_lq_sources",
                          help="""Disable cover sources that may return unreliable results (ie. Google Images).
                                  It will speed up processing and improve reliability, but may fail to find results for
                                  some difficult searches.""")
  arg_parser.add_argument("-e",
                          "--https",
                          action="store_true",
                          default=False,
                          dest="https",
                          help="Use SSL encryption (HTTPS) when available")
  arg_parser.add_argument("-v",
                          "--verbosity",
                          choices=("quiet", "warning", "normal", "debug"),
                          default="normal",
                          dest="verbosity",
                          help="Level of logging output")
  args = arg_parser.parse_args()
  args.format = os.path.splitext(args.out_filepath)[1][1:].lower()
  try:
    args.format = SUPPORTED_IMG_FORMATS[args.format]
  except KeyError:
    print("Unable to guess image format from extension, or unknown format: %s" % (args.format))
    exit(1)

  # setup logger
  logging_level = {"quiet": logging.CRITICAL + 1,
                   "warning": logging.WARNING,
                   "normal": logging.INFO,
                   "debug": logging.DEBUG}
  logging.getLogger().setLevel(logging_level[args.verbosity])
  logging.getLogger("requests").setLevel(logging.WARNING)
  logging.getLogger("urllib3").setLevel(logging.WARNING)
  if logging_level[args.verbosity] == logging.DEBUG:
    fmt = "%(threadName)s: %(message)s"
  else:
    fmt = "%(message)s"
  logging_formatter = colored_logging.ColoredFormatter(fmt=fmt)
  logging_handler = logging.StreamHandler()
  logging_handler.setFormatter(logging_formatter)
  logging.getLogger().addHandler(logging_handler)

  # main
  main(args.album,
       args.artist,
       args.format,
       args.size,
       args.size_tolerance_prct,
       args.no_lq_sources,
       args.https,
       args.out_filepath)


if __name__ == "__main__":
  cl_main()
