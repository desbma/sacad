import collections
import urllib.parse

import lxml.cssselect
import lxml.etree

from sacad.cover import CoverImageFormat, CoverImageMetadata, CoverSourceQuality, CoverSourceResult
from sacad.sources.base import CoverSource


class AmazonCdCoverSourceResult(CoverSourceResult):

  def __init__(self, *args, **kwargs):
    super().__init__(*args, source_quality=CoverSourceQuality.NORMAL, **kwargs)


class AmazonCdCoverSource(CoverSource):

  """ Cover source returning Amazon.com audio CD images. """

  TLDS = ("com", "ca", "cn", "fr", "de", "co.jp", "co.uk")
  RESULTS_SELECTOR = lxml.cssselect.CSSSelector("#resultsCol li.s-result-item")
  IMG_SELECTOR = lxml.cssselect.CSSSelector("img.s-access-image")
  PRODUCT_LINK_SELECTOR = lxml.cssselect.CSSSelector("a.s-access-detail-page")
  PRODUCT_PAGE_IMG_SELECTOR = lxml.cssselect.CSSSelector("img#landingImage")

  def __init__(self, *args, tld="com", **kwargs):
    assert(tld in __class__.TLDS)
    self.base_url = "https://www.amazon.%s/gp/search" % (tld)
    super().__init__(*args, allow_cookies=True, **kwargs)

  def getSearchUrl(self, album, artist):
    """ See CoverSource.getSearchUrl. """
    params = collections.OrderedDict()
    params["search-alias"] = "popular"
    params["field-artist"] = __class__.unaccentuate(artist.lower())
    params["field-title"] = __class__.unaccentuate(album.lower())
    params["sort"] = "relevancerank"
    return __class__.assembleUrl(self.base_url, params)

  def updateHttpHeaders(self, headers):
    """ See CoverSource.updateHttpHeaders. """
    headers["User-Agent"] = "Mozilla/5.0 Firefox/47.0"

  async def parseResults(self, api_data):
    """ See CoverSource.parseResults. """
    results = []

    # parse page
    parser = lxml.etree.HTMLParser()
    html = lxml.etree.XML(api_data.decode("utf-8", "ignore"), parser)
    result_divs = __class__.RESULTS_SELECTOR(html)
    for rank, result_div in enumerate(result_divs, 1):
      try:
        img_node = __class__.IMG_SELECTOR(result_div)[0]
      except IndexError:
        # no image for that product
        continue
      # get thumbnail & full image url
      thumbnail_url = img_node.get("src")
      url_parts = thumbnail_url.rsplit(".", 2)
      img_url = ".".join((url_parts[0], url_parts[2]))
      # assume size is fixed
      size = (500, 500)
      check_metadata = CoverImageMetadata.SIZE
      # try to get higher res image...
      if ((self.target_size > size[0]) and  # ...only if needed
              (rank <= 3)):  # and only for first 3 results because this is time
                             # consuming (1 more GET request per result)
        product_url = __class__.PRODUCT_LINK_SELECTOR(result_div)[0].get("href")
        product_url = urllib.parse.urlsplit(product_url)
        product_url_query = urllib.parse.parse_qsl(product_url.query)
        product_url_query = collections.OrderedDict(product_url_query)
        del product_url_query["qid"]  # remove timestamp from url to improve future cache hit rate
        product_url_query = urllib.parse.urlencode(product_url_query)
        product_url_no_ts = urllib.parse.urlunsplit(product_url[:3] + (product_url_query,) + product_url[4:])
        product_page_data = await self.fetchResults(product_url_no_ts)
        product_page_html = lxml.etree.XML(product_page_data.decode("latin-1"), parser)
        try:
          img_node = __class__.PRODUCT_PAGE_IMG_SELECTOR(product_page_html)[0]
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
            check_metadata = CoverImageMetadata.NONE

      # assume format is always jpg
      format = CoverImageFormat.JPEG
      # add result
      results.append(AmazonCdCoverSourceResult(img_url,
                                               size,
                                               format,
                                               thumbnail_url=thumbnail_url,
                                               source=self,
                                               rank=rank,
                                               check_metadata=check_metadata))

    return results
