#!/usr/bin/env python3

""" Smart Automatic Cover Art Downloader : search and download music album covers. """

__version__ = "2.7.1"
__author__ = "desbma"
__license__ = "MPL 2.0"

import argparse
import asyncio
import functools
import inspect
import logging
import os
from typing import Any, Optional, Sequence

from sacad import colored_logging, sources
from sacad.cover import HAS_JPEGOPTIM, HAS_OPTIPNG, SUPPORTED_IMG_FORMATS, CoverImageFormat, CoverSourceResult
from sacad.sources.base import CoverSource

COVER_SOURCE_CLASSES = {
    m[0][: -len(CoverSource.__name__)].lower(): m[1]
    for m in inspect.getmembers(sources, lambda x: inspect.isclass(x) and issubclass(x, CoverSource))
}


async def search_and_download(
    album: str,
    artist: str,
    format: CoverImageFormat,
    size: int,
    out_filepath: str,
    *,
    size_tolerance_prct: int,
    amazon_tlds: Sequence[str] = (),
    source_classes: Optional[Sequence[Any]] = None,
    preserve_format: bool = False,
) -> bool:
    """Search and download a cover, return True if success, False instead."""
    logger = logging.getLogger("Main")

    # register sources
    source_args = (size, size_tolerance_prct)
    if source_classes is None:
        source_classes = tuple(COVER_SOURCE_CLASSES.values())
    assert source_classes is not None  # makes MyPy chill
    cover_sources = [cls(*source_args) for cls in source_classes]
    if sources.AmazonCdCoverSource in source_classes:
        for tld in amazon_tlds:
            cover_sources.append(sources.AmazonCdCoverSource(*source_args, tld=tld))

    # schedule search work
    search_futures = []
    for cover_source in cover_sources:
        coroutine = cover_source.search(album, artist)
        future = asyncio.ensure_future(coroutine)
        search_futures.append(future)

    # wait for it
    await asyncio.wait(search_futures)

    # get results
    results = []
    for future in search_futures:
        source_results = future.result()
        results.extend(source_results)

    # sort results
    results = await CoverSourceResult.preProcessForComparison(results, size, size_tolerance_prct)
    results.sort(
        reverse=True,
        key=functools.cmp_to_key(
            functools.partial(
                CoverSourceResult.compare,
                target_size=size,
                size_tolerance_prct=size_tolerance_prct,
            )
        ),
    )
    if not results:
        logger.info("No results")
    else:
        for i, result in enumerate(results, 1):
            logger.debug(f"#{i:02} {result}")

    # download
    done = False
    for result in results:
        try:
            await result.get(
                format,
                size,
                size_tolerance_prct,
                out_filepath,
                preserve_format=preserve_format,
            )
        except Exception as e:
            logger.warning(f"Download of {result} failed: {e.__class__.__qualname__} {e}")
            continue
        else:
            done = True
            break

    # cleanup sessions
    close_cr = []
    for cover_source in cover_sources:
        close_cr.append(cover_source.closeSession())
    await asyncio.gather(*close_cr)

    return done


def setup_common_args(arg_parser: argparse.ArgumentParser) -> None:
    """Set up command line arguments shared between sacad and sacad_r."""
    arg_parser.add_argument(
        "-t",
        "--size-tolerance",
        type=int,
        default=25,
        dest="size_tolerance_prct",
        help="""Tolerate this percentage of size difference with the target size.
                Note that covers with size above or close to the target size will still be preferred
                if available""",
    )
    arg_parser.add_argument(
        "-a",
        "--amazon-sites",
        nargs="+",
        choices=sources.AmazonCdCoverSource.TLDS[1:],
        default=(),
        dest="amazon_tlds",
        help="""Amazon site TLDs to use as search source, in addition to amazon.com""",
    )
    arg_parser.add_argument(
        "-s",
        "--cover-sources",
        choices=tuple(COVER_SOURCE_CLASSES.keys()),
        default=tuple(COVER_SOURCE_CLASSES.keys()),
        nargs="+",
        help="Cover sources to use, if not set use all of them.",
    )
    arg_parser.add_argument(
        "-p",
        "--preserve-format",
        action="store_true",
        default=False,
        help="Preserve source image format if possible. Target format will still be prefered when sorting results.",
    )


def cl_main() -> None:
    """Command line entry point for sacad_r."""
    # parse args
    arg_parser = argparse.ArgumentParser(
        description=f"SACAD v{__version__}. Search and download an album cover.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    arg_parser.add_argument("artist", help="Artist to search for")
    arg_parser.add_argument("album", help="Album to search for")
    arg_parser.add_argument("size", type=int, help="Target image size")
    arg_parser.add_argument("out_filepath", help="Output image filepath")
    setup_common_args(arg_parser)
    arg_parser.add_argument(
        "-v",
        "--verbosity",
        choices=("quiet", "warning", "normal", "debug"),
        default="normal",
        dest="verbosity",
        help="Level of logging output",
    )
    args = arg_parser.parse_args()
    args.format = os.path.splitext(args.out_filepath)[1][1:].lower()
    try:
        args.format = SUPPORTED_IMG_FORMATS[args.format]
    except KeyError:
        print(f"Unable to guess image format from extension, or unknown format: {args.format}")
        exit(1)
    args.cover_sources = tuple(COVER_SOURCE_CLASSES[source] for source in args.cover_sources)

    # setup logger
    logging_level = {
        "quiet": logging.CRITICAL + 1,
        "warning": logging.WARNING,
        "normal": logging.INFO,
        "debug": logging.DEBUG,
    }
    logging.getLogger().setLevel(logging_level[args.verbosity])
    if logging_level[args.verbosity] == logging.DEBUG:
        fmt = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    else:
        fmt = "%(name)s: %(message)s"
    logging_formatter = colored_logging.ColoredFormatter(fmt=fmt)
    logging_handler = logging.StreamHandler()
    logging_handler.setFormatter(logging_formatter)
    logging.getLogger().addHandler(logging_handler)
    if logging_level[args.verbosity] == logging.DEBUG:
        logging.getLogger("asyncio").setLevel(logging.WARNING)
    else:
        logging.getLogger("asyncio").setLevel(logging.CRITICAL + 1)

    # display warning if optipng or jpegoptim are missing
    if not HAS_JPEGOPTIM:
        logging.getLogger("Main").warning("jpegoptim could not be found, JPEG crunching will be disabled")
    if not HAS_OPTIPNG:
        logging.getLogger("Main").warning("optipng could not be found, PNG crunching will be disabled")

    # search and download
    coroutine = search_and_download(
        args.album,
        args.artist,
        args.format,
        args.size,
        args.out_filepath,
        size_tolerance_prct=args.size_tolerance_prct,
        amazon_tlds=args.amazon_tlds,
        source_classes=args.cover_sources,
        preserve_format=args.preserve_format,
    )
    if hasattr(asyncio, "run"):
        # Python >=3.7.0
        asyncio.run(coroutine)
    else:
        future = asyncio.ensure_future(coroutine)
        asyncio.get_event_loop().run_until_complete(future)


if __name__ == "__main__":
    cl_main()
