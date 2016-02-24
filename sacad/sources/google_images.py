import collections
import json
import urllib.parse

import lxml.cssselect
import lxml.etree

from sacad.cover import CoverImageMetadata, CoverSourceQuality, CoverSourceResult, SUPPORTED_IMG_FORMATS
from sacad.sources.base import CoverSource


class GoogleImagesCoverSourceResult(CoverSourceResult):

  def __init__(self, *args, **kwargs):
    super().__init__(*args, source_quality=CoverSourceQuality.LOW, **kwargs)


class GoogleImagesWebScrapeCoverSource(CoverSource):

  """
  Cover source that scrapes Google Images search result pages.

  Google Image Search JSON API is not used because it is deprecated and Google
  is very agressively rate limiting its access.
  """

  BASE_URL = "https://www.google.com/images"

  def getSearchUrl(self, album, artist):
    """ See CoverSource.getSearchUrl. """
    # build request url
    params = collections.OrderedDict()
    params["gbv"] = "2"
    params["q"] = "\"%s\" \"%s\" front cover" % (artist.lower(), album.lower())
    if abs(self.target_size - 500) < 300:
      params["tbs"] = "isz:m"
    elif self.target_size > 800:
      params["tbs"] = "isz:l"

    return __class__.assembleUrl(__class__.BASE_URL, params)

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
      check_metadata = CoverImageMetadata.NONE
      format = metadata_json["ity"].lower()
      try:
        format = SUPPORTED_IMG_FORMATS[format]
      except KeyError:
        # format could not be identified or is unknown
        format = None
        check_metadata = CoverImageMetadata.FORMAT
      # extract size
      size = tuple(map(int, (query["w"][0], query["h"][0])))
      # extract thumbnail url
      thumbnail_url = metadata_json["tu"]
      # result
      results.append(GoogleImagesCoverSourceResult(img_url,
                                                   size,
                                                   format,
                                                   thumbnail_url=thumbnail_url,
                                                   source=self,
                                                   rank=rank,
                                                   check_metadata=check_metadata))

    return results
