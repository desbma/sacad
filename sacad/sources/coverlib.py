import collections
import operator
import re

import lxml.cssselect
import lxml.etree

from sacad.cover import CoverImageFormat, CoverSourceQuality, CoverSourceResult
from .base import CoverSource


class CoverLibCoverSourceResult(CoverSourceResult):

  def __init__(self, *args, **kwargs):
    super().__init__(*args, source_quality=CoverSourceQuality.NORMAL, **kwargs)


class CoverLibCoverSource(CoverSource):

  """ Cover source that scrapes the ecover.to site. """

  BASE_URL = "http://coverlib.com/"

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
    subresults_selector = lxml.cssselect.CSSSelector("div.defaultpanel table.Table_SimpleSearchResult tr")
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
        results.append(CoverLibCoverSourceResult(img_url,
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
        results.append(CoverLibCoverSourceResult(img_url,
                                                 size,
                                                 format,
                                                 thumbnail_url=thumbnail_url))

    return results
