import collections
import os.path
import xml.etree.ElementTree

from sacad.cover import CoverImageMetadata, CoverSourceQuality, CoverSourceResult, SUPPORTED_IMG_FORMATS
from sacad.sources.base import CoverSource, MAX_THUMBNAIL_SIZE


class LastFmCoverSourceResult(CoverSourceResult):

  def __init__(self, *args, **kwargs):
    super().__init__(*args, source_quality=CoverSourceQuality.REFERENCE, **kwargs)


class LastFmCoverSource(CoverSource):

  """
  Cover source using the official LastFM API.

  http://www.lastfm.fr/api/show?service=290
  """

  BASE_URL = "https://ws.audioscrobbler.com/2.0/"
  API_KEY = "2410a53db5c7490d0f50c100a020f359"

  SIZES = {"small": (34, 34),
           "medium": (64, 64),
           "large": (174, 174),
           "extralarge": (300, 300),
           "mega": (600, 600)}  # this is actually between 600 and 900, sometimes even more (ie 1200)

  def getSearchUrl(self, album, artist):
    """ See CoverSource.getSearchUrl. """
    # build request url
    params = collections.OrderedDict()
    params["method"] = "album.getinfo"
    params["api_key"] = __class__.API_KEY
    params["album"] = album.lower()
    params["artist"] = artist.lower()

    return __class__.assembleUrl(__class__.BASE_URL, params)

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
      if lfm_size == "mega":
        check_metadata = CoverImageMetadata.SIZE
      else:
        check_metadata = CoverImageMetadata.NONE
      try:
        size = __class__.SIZES[lfm_size]
      except KeyError:
        continue
      if (size[0] <= MAX_THUMBNAIL_SIZE) and ((thumbnail_size is None) or (size[0] < thumbnail_size)):
        thumbnail_url = img_url
        thumbnail_size = size[0]
      format = os.path.splitext(img_url)[1][1:].lower()
      format = SUPPORTED_IMG_FORMATS[format]
      results.append(LastFmCoverSourceResult(img_url,
                                             size,
                                             format,
                                             thumbnail_url=thumbnail_url,
                                             source=self,
                                             check_metadata=check_metadata))

    return results
