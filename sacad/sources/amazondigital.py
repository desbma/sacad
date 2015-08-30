import collections
import logging
import urllib.parse

import lxml.cssselect
import lxml.etree

from sacad import http
from sacad.cover import CoverImageFormat, CoverImageMetadata, CoverSourceQuality, CoverSourceResult
from sacad.sources.base import CoverSource


class AmazonDigitalCoverSourceResult(CoverSourceResult):

  def __init__(self, *args, **kwargs):
    super().__init__(*args, source_quality=CoverSourceQuality.NORMAL, **kwargs)


class AmazonDigitalCoverSource(CoverSource):

  """ Cover source returning Amazon.com digital music images. """

  BASE_URL = "https://www.amazon.com/gp"
  DYNAPI_KEY = "A17SFUTIVB227Z"

  def getSearchUrl(self, album, artist):
    """ See CoverSource.getSearchUrl. """
    url = "%s/search" % (__class__.BASE_URL)
    params = collections.OrderedDict()
    params["search-alias"] = "digital-music"
    params["field-keywords"] = " ".join(map(__class__.unaccentuate,
                                            map(str.lower,
                                                (artist, album))))
    params["sort"] = "relevancerank"
    return __class__.assembleUrl(url, params)

  def updateHttpHeaders(self, headers):
    """ See CoverSource.updateHttpHeaders. """
    pass

  def parseResults(self, api_data):
    """ See CoverSource.parseResults. """
    results = []

    # parse page
    parser = lxml.etree.HTMLParser()
    html = lxml.etree.XML(api_data.decode("utf-8"), parser)
    results_selectors = (lxml.cssselect.CSSSelector("div#dm_mp3Player div.mp3Cell"),
                         lxml.cssselect.CSSSelector("div#dm_mp3Player li.s-mp3-federated-bar-item"))
    img_selectors = (lxml.cssselect.CSSSelector("img.productImage"),
                     lxml.cssselect.CSSSelector("img.s-access-image"))
    link_selector = lxml.cssselect.CSSSelector("a")
    slice_count_to_res = {1: 600, 2: 700, 3: 1050, 4: 1400}

    for page_struct_version in range(len(results_selectors)):
      result_divs = results_selectors[page_struct_version](html)
      if result_divs:
        break

    for rank, result_div in enumerate(result_divs, 1):
      # get thumbnail & full image url
      img_node = img_selectors[page_struct_version](result_div)[0]
      thumbnail_url = img_node.get("src")
      thumbnail_url = thumbnail_url.replace("Stripe-Prime-Only", "")
      url_parts = thumbnail_url.rsplit(".", 2)
      img_url = ".".join((url_parts[0], url_parts[2]))

      # assume size is fixed
      size = (500, 500)

      # try to get higher res image...
      if self.target_size > size[0]:  # ...but only if needed
        logging.getLogger().debug("Looking for optimal subimages configuration...")
        product_url = link_selector(result_div)[0].get("href")
        product_url = urllib.parse.urlsplit(product_url)
        product_id = product_url.path.split("/")[3]

        found = False
        for slice_count in range(4, 1, -1):
          for square_sub_img in (True, False):
            if square_sub_img and (slice_count == 4):
              # unfortunately, this one is never available
              continue

            logging.getLogger().debug("Trying %u %ssquare subimages..." % (slice_count ** 2,
                                                                           "non " if not square_sub_img else ""))
            urls = tuple(self.generateImgUrls(product_id, __class__.DYNAPI_KEY, slice_count, square_sub_img))
            # this is a simple head request (no payload), so we don't rate limit
            url_ok = http.is_reachable(urls[-1], session=self.http_session)
            if not url_ok:
              # images at this size are not available
              continue

            # images at this size are available
            found = True
            break

          if found:
            break

        if found:
          img_url = urls
          size = (slice_count_to_res[slice_count],) * 2

      # assume format is always jpg
      format = CoverImageFormat.JPEG

      # add result
      results.append(AmazonDigitalCoverSourceResult(img_url,
                                                    size,
                                                    format,
                                                    thumbnail_url=thumbnail_url,
                                                    source=self,
                                                    rank=rank,
                                                    check_metadata=CoverImageMetadata.SIZE))

    return results

  def generateImgUrls(self, product_id, dynapi_key, slice_count, square_sub_img):
    """ Generate URLs for slice_count^2 subimages of a product. """
    for x in range(slice_count):
      for y in range(slice_count):
        yield ("http://z2-ec2.images-amazon.com/R/1/a=" + product_id +
               "+c=" + dynapi_key +
               "+d=_SCR%28" + str(slice_count - 1 + int(square_sub_img)) + "," + str(x) + "," + str(y) + "%29_=.jpg")
