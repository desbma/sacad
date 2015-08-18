import collections
import operator
import re
import urllib.parse

import lxml.cssselect
import lxml.etree

from sacad.cover import CoverImageFormat, CoverSourceQuality, CoverSourceResult
from sacad.sources.base import CoverSource


class CoverLibCoverSourceResult(CoverSourceResult):

  def __init__(self, *args, **kwargs):
    super().__init__(*args, source_quality=CoverSourceQuality.NORMAL, **kwargs)


class CoverLibCoverSource(CoverSource):

  """ Cover source that scrapes the coverlib.com site. """

  BASE_URL = "http://coverlib.com/"

  def getSearchUrl(self, album, artist):
    """ See CoverSource.getSearchUrl. """
    url = "%ssearch/" % (__class__.BASE_URL)
    params = collections.OrderedDict()
    params["q"] = "%s %s" % (artist.lower(), album.lower())
    params["Sektion"] = "2"
    return __class__.assembleUrl(url, params)

  def updateHttpHeaders(self, headers):
    """ See CoverSource.updateHttpHeaders. """
    pass

  def parseResults(self, api_data):
    """ See CoverSource.parseResults. """
    results = []

    # parse page
    parser = lxml.etree.HTMLParser()
    html = lxml.etree.XML(api_data.decode("latin-1"), parser)
    album_selector = lxml.cssselect.CSSSelector("div.panel-body div.row")
    cover_selector = lxml.cssselect.CSSSelector("div.col-lg-3")
    info_selector = lxml.cssselect.CSSSelector("p.visible-lg-block.thumbdescr")
    link_selector = lxml.cssselect.CSSSelector("a.dallery-item")
    size_regex = re.compile("Size: ([0-9.]+) x ([0-9.]+)px")

    rank = 1
    for album in album_selector(html):
      try:
        cover = cover_selector(album)[0]  # first cover is front cover
      except IndexError:
        # no results
        break
      desc = info_selector(cover)[0]
      desc_txt = lxml.etree.tostring(desc, encoding="unicode", method="text")

      # get resolution
      re_match = size_regex.search(desc_txt)
      size = tuple(map(int,
                       map(operator.methodcaller("replace", ".", ""),
                           re_match.group(1, 2))))

      # get thumbnail url
      link = link_selector(cover)[0]
      thumbnail_url = link.find("img").get("src")
      if not urllib.parse.urlparse(thumbnail_url).netloc:
        # make relative url absolute
        thumbnail_url = urllib.parse.urljoin(__class__.BASE_URL, thumbnail_url)

      # deduce img url without downloading subpage
      cover_id = int(thumbnail_url.rsplit(".", 1)[0].rsplit("/", 1)[1])
      cover_name = link.get("href").rsplit(".", 1)[0].rsplit("/", 1)[1]
      img_url = "%sDownload/%u/%s-Front.JPG" % (__class__.BASE_URL, cover_id, cover_name)

      # assume format is always jpg
      format = CoverImageFormat.JPEG

      # add result
      results.append(CoverLibCoverSourceResult(img_url,
                                               size,
                                               format,
                                               thumbnail_url=thumbnail_url,
                                               source=self,
                                               rank=rank))
      rank += 1

    return results
