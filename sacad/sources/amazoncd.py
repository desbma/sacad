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

  def __init__(self, *args, tld="com", **kwargs):
    assert(tld in __class__.TLDS)
    self.base_url = "https://www.amazon.%s/gp/search" % (tld)
    super().__init__(*args, **kwargs)

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
    pass

  def parseResults(self, api_data):
    """ See CoverSource.parseResults. """
    results = []

    # parse page
    parser = lxml.etree.HTMLParser()
    html = lxml.etree.XML(api_data.decode("utf-8"), parser)
    results_selector = lxml.cssselect.CSSSelector("#atfResults li.s-result-item")
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
      check_metadata = CoverImageMetadata.SIZE
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
            check_metadata = CoverImageMetadata.NONE
          if not cache_hit:
            # add cache entry only when parsing is successful
            CoverSource.api_cache[product_url] = product_page_data
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
