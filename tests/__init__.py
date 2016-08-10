#!/usr/bin/env python3

import contextlib
import logging
import socket
import unittest
import unittest.mock
import urllib.parse

import PIL.Image
import requests
import web_cache

import sacad


web_cache.DISABLE_PERSISTENT_CACHING = True


def is_internet_reachable():
  try:
    # open TCP socket to Google DNS server
    with socket.create_connection(("8.8.8.8", 53)):
      pass
  except OSError as e:
    if e.errno == 101:
      return False
    raise
  return True


def download(url, filepath):
  with contextlib.closing(requests.get(url, timeout=5, verify=False, stream=True)) as response:
    response.raise_for_status()
    with open(filepath, "wb") as f:
      for chunk in response.iter_content(2 ** 14):
        f.write(chunk)


@unittest.skipUnless(is_internet_reachable(), "Need Internet access")
class TestSacad(unittest.TestCase):

  @staticmethod
  def getImgInfo(img_filepath):
    with open(img_filepath, "rb") as img_file:
      img = PIL.Image.open(img_file)
      format = img.format.lower()
      format = sacad.SUPPORTED_IMG_FORMATS[format]
      width, height = img.size
    return format, width, height

  def test_getMasterOfPuppetsCover(self):
    """ Search and download cover for 'Master of Puppets' with different parameters. """
    for format in sacad.cover.CoverImageFormat:
      for size in (300, 600, 1200):
        for size_tolerance in (0, 25, 50):
          with sacad.mkstemp_ctx.mkstemp(prefix="sacad_test_",
                                         suffix=".%s" % (format.name.lower())) as tmp_filepath:
            sacad.search_and_download("Master of Puppets",
                                      "Metallica",
                                      format,
                                      size,
                                      size_tolerance,
                                      (),
                                      False,
                                      tmp_filepath)
            out_format, out_width, out_height = __class__.getImgInfo(tmp_filepath)
            self.assertEqual(out_format, format)
            self.assertLessEqual(out_width, size * (100 + size_tolerance) / 100)
            self.assertGreaterEqual(out_width, size * (100 - size_tolerance) / 100)
            self.assertLessEqual(out_height, size * (100 + size_tolerance) / 100)
            self.assertGreaterEqual(out_height, size * (100 - size_tolerance) / 100)

  def test_getImageUrlMetadata(self):
    """ Download the beginning of image files to guess their format and resolution. """
    refs = {"https://www.nuclearblast.de/static/articles/152/152118.jpg/1000x1000.jpg": (sacad.cover.CoverImageFormat.JPEG,
                                                                                         (700, 700),
                                                                                         5),
            "http://img2-ak.lst.fm/i/u/55ad95c53e6043e3b150ba8a0a3b20a1.png": (sacad.cover.CoverImageFormat.PNG,
                                                                               (600, 600),
                                                                               1)}
    for url, (ref_fmt, ref_size, block_read) in refs.items():
      sacad.CoverSourceResult.getImageMetadata = unittest.mock.Mock(wraps=sacad.CoverSourceResult.getImageMetadata)
      source = unittest.mock.Mock()
      source.http_session = sacad.http_helpers.session()
      cover = sacad.CoverSourceResult(url,
                                      None,
                                      None,
                                      source=source,
                                      thumbnail_url=None,
                                      source_quality=None,
                                      check_metadata=sacad.cover.CoverImageMetadata.ALL)
      cover.updateImageMetadata()
      self.assertEqual(cover.size, ref_size)
      self.assertEqual(cover.format, ref_fmt)
      self.assertGreaterEqual(sacad.CoverSourceResult.getImageMetadata.call_count, 0)
      self.assertLessEqual(sacad.CoverSourceResult.getImageMetadata.call_count, block_read)

  def test_compareImageSignatures(self):
    """ Compare images using their signatures. """
    urls = ("http://wac.450f.edgecastcdn.net/80450F/kool1017.com/files/2013/09/cover_highway_to_hell_500x500.jpg",
            "http://www.jesus-is-savior.com/Evils%20in%20America/Rock-n-Roll/highway_to_hell-large.jpg",
            "http://i158.photobucket.com/albums/t113/gatershanks/Glee%20Alternative%20Song%20Covers/1x14%20Hell%20O/1x14Hell-O-HighwayToHell.jpg")
    with sacad.mkstemp_ctx.mkstemp(suffix="jpg") as temp_filepath1, \
            sacad.mkstemp_ctx.mkstemp(suffix="jpg") as temp_filepath2, \
            sacad.mkstemp_ctx.mkstemp(suffix="jpg") as temp_filepath3:
      img_sig = {}
      for i, (url, filepath) in enumerate(zip(urls, (temp_filepath1, temp_filepath2, temp_filepath3))):
        download(url, filepath)
        with open(filepath, "rb") as img_file:
          img_data = img_file.read()
          img_sig[i] = sacad.CoverSourceResult.computeImgSignature(img_data)
      self.assertTrue(sacad.CoverSourceResult.areImageSigsSimilar(img_sig[0], img_sig[1]))
      self.assertTrue(sacad.CoverSourceResult.areImageSigsSimilar(img_sig[1], img_sig[0]))
      self.assertFalse(sacad.CoverSourceResult.areImageSigsSimilar(img_sig[0], img_sig[2]))
      self.assertFalse(sacad.CoverSourceResult.areImageSigsSimilar(img_sig[1], img_sig[2]))
      self.assertFalse(sacad.CoverSourceResult.areImageSigsSimilar(img_sig[2], img_sig[0]))
      self.assertFalse(sacad.CoverSourceResult.areImageSigsSimilar(img_sig[2], img_sig[1]))

  def test_coverSources(self):
    """ Check all sources return valid results with different parameters. """
    for size in range(300, 1200 + 1, 300):
      source_args = (size, 0)
      sources = [sacad.sources.LastFmCoverSource(*source_args),
                 sacad.sources.GoogleImagesWebScrapeCoverSource(*source_args),
                 sacad.sources.AmazonDigitalCoverSource(*source_args)]
      sources.extend(sacad.sources.AmazonCdCoverSource(*source_args, tld=tld) for tld in sacad.sources.AmazonCdCoverSource.TLDS)
      for source in sources:
        for artist, album in zip(("Michael Jackson", "Björk"), ("Thriller", "Vespertine")):
          results = source.search(album, artist)
          results = sacad.CoverSourceResult.preProcessForComparison(results, size, 0)
          if not (((size > 500) and isinstance(source, sacad.sources.AmazonCdCoverSource)) or
                  ((size > 500) and isinstance(source, sacad.sources.LastFmCoverSource)) or
                  (isinstance(source, sacad.sources.AmazonCdCoverSource) and (artist == "Björk") and
                   (urllib.parse.urlsplit(source.base_url).netloc.rsplit(".", 1)[-1] == "cn"))):
            self.assertGreaterEqual(len(results), 1, "%s %s %s %u" % (source.__class__.__name__,
                                                                      artist,
                                                                      album,
                                                                      size))
          for result in results:
            self.assertTrue(result.urls)
            self.assertIn(result.format, sacad.cover.CoverImageFormat)
            self.assertGreaterEqual(result.size[0], size)

    # test for specific cover not available on amazon.com, but on amazon.de
    size = 290
    source = sacad.sources.AmazonCdCoverSource(size, 0, tld="de")
    results = source.search("Dream Dance 5", "Various")
    self.assertGreaterEqual(len(results), 1)
    for result in results:
      self.assertTrue(result.urls)
      self.assertIn(result.format, sacad.cover.CoverImageFormat)
      self.assertGreaterEqual(result.size[0], size)

  def test_unaccentuate(self):
    self.assertEqual(sacad.sources.base.CoverSource.unaccentuate("EéeAàaOöoIïi"), "EeeAaaOooIii")

  def test_is_square(self):
    for x in range(1, 100):
      if x in (1, 4, 9, 16, 25, 36, 49, 64, 81):
        self.assertTrue(sacad.cover.is_square(x), x)
      else:
        self.assertFalse(sacad.cover.is_square(x), x)


if __name__ == "__main__":
  # logging
  #logging.getLogger().setLevel(logging.DEBUG)
  logging.getLogger().setLevel(logging.CRITICAL + 1)

  # run tests
  unittest.main()
