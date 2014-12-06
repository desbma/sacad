#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import socket
import unittest
import unittest.mock

import PIL.Image
import requests

import sacad


sacad.web_cache.DISABLE_PERSISTENT_CACHING = True


def is_internet_reachable():
  try:
    # open TCP socket to Google DNS server
    socket.create_connection(("8.8.8.8", 53))
  except OSError as e:
    if e.errno == 101:
      return False
    raise
  return True


def download(url, filepath):
  response = requests.get(url, timeout=5, verify=False, stream=True)
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
    for format in sacad.CoverImageFormat:
      for size in (300, 600, 1200):
        for size_tolerance in (0, 25, 50):
          for prefer_https in (True, False):
            with sacad.mkstemp_ctx.mkstemp(prefix="sacad_test_",
                                           suffix=".%s" % (format.name.lower())) as tmp_filepath:
              sacad.main("Master of Puppets", "Metallica", format, size, size_tolerance, False, prefer_https, tmp_filepath)
              out_format, out_width, out_height = __class__.getImgInfo(tmp_filepath)
              self.assertEqual(out_format, format)
              self.assertLessEqual(out_width, size * (100 + size_tolerance) / 100)
              self.assertGreaterEqual(out_width, size * (100 - size_tolerance) / 100)
              self.assertLessEqual(out_height, size * (100 + size_tolerance) / 100)
              self.assertGreaterEqual(out_height, size * (100 - size_tolerance) / 100)

  def test_getImageUrlMetadata(self):
    """ Download the beginning of an image file to guess its format and resolution. """
    url = "http://lacuriosphere.fr/wp-content/uploads/2013/12/mountains-and-clouds.jpg"
    sacad.CoverSourceResult.getImageMetadata = unittest.mock.Mock(wraps=sacad.CoverSourceResult.getImageMetadata)
    cover = sacad.CoverSourceResult(url, None, None, thumbnail_url=None, source_quality=None)
    cover.updateImageMetadata()
    self.assertEqual(cover.size, (1600, 1200))
    self.assertEqual(cover.format, sacad.CoverImageFormat.JPEG)
    self.assertGreaterEqual(sacad.CoverSourceResult.getImageMetadata.call_count, 0)
    self.assertLessEqual(sacad.CoverSourceResult.getImageMetadata.call_count, 3)

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
      for prefer_https in (True, False):
        sources = (sacad.LastFmCoverSource(size, 0, prefer_https),
                   sacad.CoverParadiseCoverSource(size, 0, prefer_https),
                   sacad.AmazonCoverSource(size, 0, prefer_https),
                   sacad.GoogleImagesWebScrapeCoverSource(size, 0, prefer_https))
        for source in sources:
          for artist, album in zip(("Michael Jackson", "Björk"), ("Thriller", "Vespertine")):
            results = source.search(album, artist)
            results = sacad.CoverSourceResult.preProcessForComparison(results, size, 0)
            if not (((size > 500) and (source is sources[2])) or
                    ((size > 600) and (source is sources[0])) or
                    ((size >= 1200) and (source is sources[1]) and (artist == "Björk"))):
              self.assertGreaterEqual(len(results), 1)
            for result in results:
              self.assertTrue(result.url)
              self.assertIn(result.format, sacad.CoverImageFormat)
              self.assertGreaterEqual(result.size[0], size)


if __name__ == "__main__":
  # logging
  # logging.getLogger().setLevel(logging.DEBUG)
  logging.getLogger().setLevel(logging.CRITICAL + 1)

  # run tests
  unittest.main()
