import concurrent.futures
import contextlib
import enum
import io
import itertools
import logging
import math
import mimetypes
import operator
import os
import pickle
import shutil
import subprocess

import appdirs
import PIL.Image
import PIL.ImageFile
import PIL.ImageFilter

from sacad import http
from sacad import mkstemp_ctx
from sacad import web_cache


CoverImageFormat = enum.Enum("CoverImageFormat", ("JPEG", "PNG"))

CoverSourceQuality = enum.Enum("CoverSourceQuality", ("LOW", "NORMAL", "REFERENCE"))

CoverImageMetadata = enum.IntEnum("CoverImageMetadata",
                                  (("NONE", 0),
                                   ("FORMAT", 1),
                                   ("SIZE", 2),
                                   ("ALL", 3)))

HAS_JPEGOPTIM = shutil.which("jpegoptim") is not None
HAS_OPTIPNG = shutil.which("optipng") is not None
SUPPORTED_IMG_FORMATS = {"jpg": CoverImageFormat.JPEG,
                         "jpeg": CoverImageFormat.JPEG,
                         "png": CoverImageFormat.PNG}


def is_square(x):
  """ Return True if integer x is a perfect square, False otherwise. """
  sqrt = math.sqrt(x)
  return (sqrt == math.trunc(sqrt))


class CoverSourceResult:

  """ Cover image returned by a source, candidate to be downloaded. """

  MAX_FILE_METADATA_PEEK_SIZE = 2 ** 15
  IMG_SIG_SIZE = 16

  def __init__(self, urls, size, format, *, thumbnail_url, source, source_quality, rank=None,
               check_metadata=CoverImageMetadata.NONE):
    """
    Args:
      urls: Cover image file URL. Can be a tuple of URLs of images to be joined
      size: Cover size as a (with, height) tuple
      format: Cover image format as a CoverImageFormat enum, or None if unknown
      thumbnail_url: Cover thumbnail image file URL, or None if not available
      source: Cover source object that produced this result
      source_quality: Quality of the cover's source as a CoverSourceQuality enum value
      rank: Integer ranking of the cover in the other results from the same source, or None if not available
      check_metadata: If != 0, hint that the format and/or size parameters are not reliable and must be double checked
    """
    if not isinstance(urls, str):
      self.urls = urls
    else:
      self.urls = (urls,)
    self.size = size
    self.format = format
    self.thumbnail_url = thumbnail_url
    self.thumbnail_sig = None
    self.source = source
    self.source_quality = source_quality
    self.rank = rank
    self.check_metadata = check_metadata
    self.is_similar_to_reference = False
    self.is_only_reference = False
    if not hasattr(__class__, "image_cache"):
      cache_filepath = os.path.join(appdirs.user_cache_dir(appname="sacad",
                                                           appauthor=False),
                                    "sacad-cache.sqlite")
      os.makedirs(os.path.dirname(cache_filepath), exist_ok=True)
      __class__.image_cache = web_cache.ThreadedWebCache(cache_filepath,
                                                         "cover_image_data",
                                                         caching_strategy=web_cache.CachingStrategy.LRU,
                                                         expiration=60 * 60 * 24 * 365)  # 1 year
      __class__.metadata_cache = web_cache.ThreadedWebCache(cache_filepath,
                                                            "cover_metadata",
                                                            caching_strategy=web_cache.CachingStrategy.LRU,
                                                            expiration=60 * 60 * 24 * 365)  # 1 year
      for cache, cache_name in zip((__class__.image_cache, __class__.metadata_cache),
                                   ("cover_image_data", "cover_metadata")):
        purged_count = cache.purge()
        logging.getLogger().debug("%u obsolete entries have been removed from cache '%s'" % (purged_count, cache_name))
        row_count = len(cache)
        logging.getLogger().debug("Cache '%s' contains %u entries" % (cache_name, row_count))

  def __str__(self):
    s = "%s '%s'" % (self.__class__.__name__, self.urls[0])
    if len(self.urls) > 1:
      s += " [x%u]" % (len(self.urls))
    return s

  def get(self, target_format, target_size, size_tolerance_prct, out_filepath):
    """ Download cover and process it. """
    if self.source_quality.value <= CoverSourceQuality.LOW.value:
      logging.getLogger().warning("Cover is from a potentially unreliable source and may be unrelated to the search")

    images_data = []
    for i, url in enumerate(self.urls):
      cache_miss = True
      try:
        image_data = __class__.image_cache[url]
      except KeyError:
        # cache miss
        pass
      else:
        # cache hit
        logging.getLogger().info("Got data for URL '%s' from cache" % (url))
        cache_miss = False

      if cache_miss:
        # download
        logging.getLogger().info("Downloading cover '%s' (part %u/%u)..." % (url, i + 1, len(self.urls)))
        image_data = http.query(url,
                                session=self.source.http_session,
                                verify=False)

        # crunch image
        image_data = __class__.crunch(image_data, self.format)

        # save it to cache
        __class__.image_cache[url] = image_data

      # append for multi images
      images_data.append(image_data)

    need_format_change = (self.format != target_format)
    need_size_change = ((max(self.size) > target_size) and
                        (abs(max(self.size) - target_size) >
                         target_size * size_tolerance_prct / 100))
    need_join = len(images_data) > 1
    if need_join or need_format_change or need_size_change:
      # post process
      image_data = self.postProcess(images_data,
                                    target_format if need_format_change else None,
                                    target_size if need_size_change else None)

      # crunch image again
      image_data = __class__.crunch(image_data, target_format)

    # write it
    with open(out_filepath, "wb") as file:
      file.write(image_data)

  def postProcess(self, images_data, new_format, new_size):
    """ Convert image binary data to a target format and/or size (None if no conversion needed), and return the processed data. """
    if len(images_data) == 1:
      in_bytes = io.BytesIO(images_data[0])
      img = PIL.Image.open(in_bytes)

    else:
      # images need to be joined before further processing
      logging.getLogger().info("Joining %u images..." % (len(images_data)))
      # TODO find a way to do this losslessly for JPEG
      new_img = PIL.Image.new("RGB", self.size)
      assert(is_square(len(images_data)))
      sq = int(math.sqrt(len(images_data)))

      images_data_it = iter(images_data)
      img_sizes = {}
      for x in range(sq):
        for y in range(sq):
          current_image_data = next(images_data_it)
          img_stream = io.BytesIO(current_image_data)
          img = PIL.Image.open(img_stream)
          img_sizes[(x, y)] = img.size
          box = [0, 0]
          if x > 0:
            for px in range(x):
              box[0] += img_sizes[(px, y)][0]
          if y > 0:
            for py in range(y):
              box[1] += img_sizes[(x, py)][1]
          box.extend((box[0] + img.size[0], box[1] + img.size[1]))
          new_img.paste(img, box=tuple(box))
      img = new_img

    out_bytes = io.BytesIO()
    if new_size is not None:
      logging.getLogger().info("Resizing from %ux%u to %ux%u..." % (self.size[0], self.size[1], new_size, new_size))
      img = img.resize((new_size, new_size))
      # apply unsharp filter to remove resize blur (equivalent to (images/graphics)magick -unsharp 1.5x1+0.7+0.02)
      # we don't use PIL.ImageFilter.SHARPEN or PIL.ImageEnhance.Sharpness because we want precise control over
      # parameters
      unsharper = PIL.ImageFilter.UnsharpMask(radius=1.5, percent=70, threshold=5)
      img = img.filter(unsharper)
    if new_format is not None:
      logging.getLogger().info("Converting to %s..." % (new_format.name.upper()))
      target_format = new_format
    else:
      target_format = self.format
    img.save(out_bytes, format=target_format.name, quality=90, optimize=True)
    return out_bytes.getvalue()

  def updateImageMetadata(self):
    """ Partially download image file(s) to get its real metadata, or get it from cache. """
    assert(self.needMetadataUpdate())

    width_sum, height_sum = 0, 0
    format, width, height = None, None, None

    idxs = []
    # only download metadata for the needed images to get full size
    assert(is_square(len(self.urls)))
    sq = int(math.sqrt(len(self.urls)))
    for x in range(sq):
      for y in range(sq):
        if (x == 0) or (y == 0):
          idxs.append((x * sq + y, x, y))

    for idx, x, y in idxs:
      url = self.urls[idx]

      try:
        format, width, height = pickle.loads(__class__.metadata_cache[url])
      except KeyError:
        # cache miss
        pass
      except Exception as e:
        logging.getLogger().warning("Unable to load metadata for URL '%s' from cache: %s %s" % (url,
                                                                                                e.__class__.__qualname__,
                                                                                                e))
      else:
        # cache hit
        logging.getLogger().debug("Got metadata for URL '%s' from cache" % (url))
        if format is not None:
          self.check_metadata &= ~CoverImageMetadata.FORMAT
        if (width is not None) and (height is not None):
          self.check_metadata &= ~CoverImageMetadata.SIZE

      if self.needMetadataUpdate():
        # download
        logging.getLogger().debug("Downloading file header for URL '%s'..." % (url))
        try:
          metadata = None
          img_data = bytearray()
          with contextlib.closing(http.fast_streamed_query(url,
                                                           session=self.source.http_session,
                                                           verify=False)) as response:
            if (self.check_metadata & CoverImageMetadata.FORMAT) != 0:
              # try to get format from response mime type
              try:
                content_type = response.headers["Content-Type"]
                ext = mimetypes.guess_extension(content_type, strict=False)
                if ext is not None:
                  format = SUPPORTED_IMG_FORMATS[ext[1:]]
                  self.check_metadata &= ~CoverImageMetadata.FORMAT
              except KeyError:
                pass
            if self.needMetadataUpdate():
              for new_img_data in response.iter_content(chunk_size=2 ** 12):
                img_data.extend(new_img_data)
                metadata = __class__.getImageMetadata(img_data)
                if len(img_data) >= CoverSourceResult.MAX_FILE_METADATA_PEEK_SIZE:
                  break
                if metadata is not None:
                  format, width, height = metadata
                  self.check_metadata = CoverImageMetadata.NONE
                  break
          if self.needMetadataUpdate():
            # if we get here, file is probably not reachable, or not even an image
            logging.getLogger().debug("Unable to get file metadata from file  or HTTP headers for URL '%s', \
                                       skipping this result" % (url))
            return self  # for use with concurrent.futures
        except Exception as e:
          logging.getLogger().debug("Unable to get file metadata for URL '%s' (%s %s), \
                                     falling back to API data" % (url,
                                                                  e.__class__.__qualname__,
                                                                  e))
          self.check_metadata = CoverImageMetadata.NONE
          return self  # for use with concurrent.futures

        # save it to cache
        __class__.metadata_cache[url] = pickle.dumps((format, width, height))

      # sum sizes
      if (width is not None) and (height is not None):
        if y == 0:
          width_sum += width
        if x == 0:
          height_sum += height

    self.check_metadata = CoverImageMetadata.NONE
    self.format = format
    if (width_sum > 0) and (height_sum > 0):
      self.size = (width_sum, height_sum)

    return self  # for use with concurrent.futures

  def needMetadataUpdate(self):
    """ Return True if image metadata needs to be checked, False instead. """
    return self.check_metadata != CoverImageMetadata.NONE

  def updateSignature(self):
    """ Calculate a cover's "signature" using its thumbnail url. """
    if self.thumbnail_sig is not None:
      # TODO understand how it is possible to get here (only with Python 3.4 it seems)
      return self

    if self.thumbnail_url is None:
      logging.getLogger().warning("No thumbnail available for %s" % (self))
      return

    cache_miss = True
    try:
      image_data = __class__.image_cache[self.thumbnail_url]
    except KeyError:
      # cache miss
      pass
    else:
      # cache hit
      logging.getLogger().debug("Got data for URL '%s' from cache" % (self.thumbnail_url))
      cache_miss = False

    if cache_miss:
      # download
      logging.getLogger().info("Downloading cover thumbnail '%s'..." % (self.thumbnail_url))
      try:
        image_data = http.query(self.thumbnail_url,
                                session=self.source.http_session)
      except Exception as e:
        logging.getLogger().warning("Download of '%s' failed: %s %s" % (self.thumbnail_url,
                                                                        e.__class__.__qualname__,
                                                                        e))
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
    Covers with sizes under the target size (+- configured tolerance) are excluded before comparison.
    The following factors are used in order:
      1. Prefer approximately square covers
      2. Prefer covers of "reference" source quality
      3. Prefer covers similar to the reference cover
      4. Prefer size above target size
      5. Prefer covers of reliable source
      6. Prefer best ranked cover
    If all previous factors do not allow sorting of two results (very unlikely):
      7. Prefer covers having the target size
      8. Prefer covers with less images to join
      9. Prefer PNG covers
      10. Prefer exactly square covers

    We don't overload the __lt__ operator because we need to pass the target_size parameter.

    """
    for c in (first, second):
      assert(c.format is not None)
      assert(isinstance(c.size[0], int) and isinstance(c.size[1], int))

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
      return -1 if (qs1 < qs2) else 1

    # prefer best ranked
    if ((first.rank is not None) and
            (second.rank is not None) and
            (first.__class__ is second.__class__) and
            (first.rank != second.rank)):
      return -1 if (first.rank > second.rank) else 1

    # prefer covers with less images to join
    ic1 = len(first.urls)
    ic2 = len(second.urls)
    if ic1 != ic2:
      return -1 if (ic1 > ic2) else 1

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
        cmd = ["optipng", "-quiet", "-o5"]  # this can be very slow for big PNG files
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

    # remove duplicates
    no_dup_results = []
    for result in results:
      is_dup = False
      for result_comp in results:
        if ((result_comp is not result) and
            (result_comp.urls == result.urls) and
            (__class__.compare(result,
                               result_comp,
                               target_size=target_size,
                               size_tolerance_prct=size_tolerance_prct) < 0)):
          is_dup = True
          break
      if not is_dup:
        no_dup_results.append(result)
    dup_count = len(results) - len(no_dup_results)
    if dup_count > 0:
      logging.getLogger().info("Removed %u duplicate results" % (dup_count))
      results = no_dup_results

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
