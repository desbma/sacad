#!/usr/bin/env python3

""" Smart Automatic Cover Art Downloader : search and download music album covers. """

__version__ = "1.5.0"
__author__ = "desbma"
__license__ = "MPL 2.0"

import argparse
import functools
import logging
import os
import sys

from sacad import colored_logging
from sacad import sources
from sacad.cover import CoverSourceResult, HAS_JPEGOPTIM, HAS_OPTIPNG, SUPPORTED_IMG_FORMATS


def main(album, artist, format, size, size_tolerance_prct, amazon_tlds, no_lq_sources, out_filepath):
  # display warning if optipng or jpegoptim are missing
  if not HAS_JPEGOPTIM:
    logging.getLogger().warning("jpegoptim could not be found, JPEG crunching will be disabled")
  if not HAS_OPTIPNG:
    logging.getLogger().warning("optipng could not be found, PNG crunching will be disabled")

  # register sources
  source_args = (size, size_tolerance_prct)
  cover_sources = [sources.LastFmCoverSource(*source_args),
                   sources.CoverLibCoverSource(*source_args),
                   sources.AmazonCdCoverSource(*source_args),
                   sources.AmazonDigitalCoverSource(*source_args)]
  for tld in amazon_tlds:
    cover_sources.append(sources.AmazonCdCoverSource(*source_args, tld=tld))
  if not no_lq_sources:
    cover_sources.append(sources.GoogleImagesWebScrapeCoverSource(*source_args))

  # search
  results = []
  for cover_source in cover_sources:
    results.extend(cover_source.search(album, artist))

  # sort results
  results = CoverSourceResult.preProcessForComparison(results, size, size_tolerance_prct)
  results.sort(reverse=True,
               key=functools.cmp_to_key(functools.partial(CoverSourceResult.compare,
                                                          target_size=size,
                                                          size_tolerance_prct=size_tolerance_prct)))
  if not results:
    logging.getLogger().info("No results")

  # download
  for result in results:
    try:
      result.get(format, size, size_tolerance_prct, out_filepath)
    except Exception as e:
      logging.getLogger().warning("Download of %s failed: %s %s" % (result,
                                                                    e.__class__.__qualname__,
                                                                    e))
      continue
    else:
      break


def cl_main():
  # parse args
  arg_parser = argparse.ArgumentParser(description="SACAD v%s. Search and download an album cover." % (__version__),
                                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
  arg_parser.add_argument("artist",
                          help="Artist to search for")
  arg_parser.add_argument("album",
                          help="Album to search for")
  arg_parser.add_argument("size",
                          type=int,
                          help="Target image size")
  arg_parser.add_argument("out_filepath",
                          help="Output image file")
  arg_parser.add_argument("-t",
                          "--size-tolerance",
                          type=int,
                          default=25,
                          dest="size_tolerance_prct",
                          help="""Tolerate this percentage of size difference with the target size.
                                  Note that covers with size above or close to the target size will still be preferred
                                  if available""")
  arg_parser.add_argument("-a",
                          "--amazon-sites",
                          nargs="+",
                          choices=sources.AmazonCdCoverSource.TLDS[1:],
                          default=(),
                          dest="amazon_tlds",
                          help="""Amazon site TLDs to use as search source, in addition to amazon.com""")
  arg_parser.add_argument("-d",
                          "--disable-low-quality-sources",
                          action="store_true",
                          default=False,
                          dest="no_lq_sources",
                          help="""Disable cover sources that may return unreliable results (ie. Google Images).
                                  It will speed up search and improve reliability, but may fail to find results for
                                  some difficult searches.""")
  arg_parser.add_argument("-v",
                          "--verbosity",
                          choices=("quiet", "warning", "normal", "debug"),
                          default="normal",
                          dest="verbosity",
                          help="Level of logging output")
  args = arg_parser.parse_args()
  args.format = os.path.splitext(args.out_filepath)[1][1:].lower()
  try:
    args.format = SUPPORTED_IMG_FORMATS[args.format]
  except KeyError:
    print("Unable to guess image format from extension, or unknown format: %s" % (args.format))
    exit(1)

  # setup logger
  logging_level = {"quiet": logging.CRITICAL + 1,
                   "warning": logging.WARNING,
                   "normal": logging.INFO,
                   "debug": logging.DEBUG}
  logging.getLogger().setLevel(logging_level[args.verbosity])
  if logging_level[args.verbosity] == logging.DEBUG:
    fmt = "%(threadName)s: %(message)s"
  else:
    fmt = "%(message)s"
  logging_formatter = colored_logging.ColoredFormatter(fmt=fmt)
  logging_handler = logging.StreamHandler()
  logging_handler.setFormatter(logging_formatter)
  logging.getLogger().addHandler(logging_handler)

  # main
  main(args.album,
       args.artist,
       args.format,
       args.size,
       args.size_tolerance_prct,
       args.amazon_tlds,
       args.no_lq_sources,
       args.out_filepath)


if getattr(sys, "frozen", False):
  # fix for cx_freeze generated executable not finding certs
  os.environ["REQUESTS_CA_BUNDLE"] = os.path.join(os.path.dirname(sys.executable), "cacert.pem")


if __name__ == "__main__":
  cl_main()
