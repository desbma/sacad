#!/usr/bin/env python3

""" Recursively search and download album covers for a music library. """

import argparse
import asyncio
import contextlib
import base64
import collections
import inspect
import itertools
import logging
import operator
import os
import string
import tempfile

import mutagen
import tqdm
import unidecode

import sacad
from sacad import colored_logging
from sacad import tqdm_logging


EMBEDDED_ALBUM_ART_SYMBOL = "+"
AUDIO_EXTENSIONS = frozenset(("aac",
                              "ape",
                              "flac",
                              "m4a",
                              "mp3",
                              "mp4",
                              "ogg",
                              "oga",
                              "opus",
                              "wv"))

Metadata = collections.namedtuple("Metadata",
                                  ("artist",
                                   "album",
                                   "has_embedded_cover"))


# TODO use a dataclasses.dataclass when Python < 3.7 is dropped
class Work:

  """ Represent a single search & download work item. """

  def __init__(self, cover_filepath, audio_filepaths, metadata):
    self.cover_filepath = cover_filepath
    self.tmp_cover_filepath = None
    self.audio_filepaths = audio_filepaths
    self.metadata = metadata

  def __repr__(self):
    return "<%s cover_filepath=%s tmp_cover_filepath=%s " \
           "audio_filepaths=%s metadata=%s>" % (__class__.__qualname__,
                                                repr(self.cover_filepath),
                                                repr(self.tmp_cover_filepath),
                                                repr(self.audio_filepaths),
                                                repr(self.metadata))

  def __str__(self):
    return "cover for '%s' by '%s' from %s" % (self.metadata.album,
                                               self.metadata.artist,
                                               ", ".join(map(repr, self.audio_filepaths)))

  def __eq__(self, other):
    if not isinstance(other, __class__):
      return False
    return ((self.cover_filepath == other.cover_filepath) and
            (self.tmp_cover_filepath == other.tmp_cover_filepath) and
            (self.audio_filepaths == other.audio_filepaths) and
            (self.metadata == other.metadata))


def analyze_lib(lib_dir, cover_pattern, *, ignore_existing=False, full_scan=False):
  """ Recursively analyze library, and return a list of work. """
  work = []
  stats = collections.OrderedDict(((k, 0) for k in("files", "albums", "missing covers", "errors")))
  with tqdm.tqdm(desc="Analyzing library",
                 unit="dir",
                 postfix=stats) as progress, \
          tqdm_logging.redirect_logging(progress):
    for rootpath, rel_dirpaths, rel_filepaths in os.walk(lib_dir):
      new_work = analyze_dir(stats,
                             rootpath,
                             rel_filepaths,
                             cover_pattern,
                             ignore_existing=ignore_existing,
                             full_scan=full_scan)
      progress.set_postfix(stats, refresh=False)
      progress.update(1)
      work.extend(new_work)
  return work


def get_file_metadata(audio_filepath):
  """ Get a Metadata object for this file or None. """
  try:
    mf = mutagen.File(audio_filepath)
  except Exception:
    return
  if mf is None:
    return

  # artist
  for key in ("albumartist", "artist",  # ogg
              "TPE1", "TPE2",  # mp3
              "aART", "\xa9ART"):  # mp4
    try:
      val = mf.get(key, None)
    except ValueError:
      val = None
    if val is not None:
      artist = val[-1]
      break
  else:
    return

  # album
  for key in ("_album", "album",  # ogg
              "TALB",  # mp3
              "\xa9alb"):  # mp4
    try:
      val = mf.get(key, None)
    except ValueError:
      val = None
    if val is not None:
      album = val[-1]
      break
  else:
    return

  # album art
  if isinstance(mf.tags, mutagen._vorbis.VComment):
    has_embedded_cover = "metadata_block_picture" in mf
  elif isinstance(mf.tags, mutagen.id3.ID3):
    has_embedded_cover = any(map(operator.methodcaller("startswith", "APIC:"), mf.keys()))
  elif isinstance(mf.tags, mutagen.mp4.MP4Tags):
    has_embedded_cover = "covr" in mf
  else:
    return

  return Metadata(artist, album, has_embedded_cover)


def get_dir_metadata(audio_filepaths, *, full_scan=False):
  """ Build a dict of Metadata to audio filepath list by analyzing audio files. """
  r = collections.defaultdict(list)

  audio_filepaths = tuple(sorted(audio_filepaths))
  for audio_filepath in audio_filepaths:
    file_metadata = get_file_metadata(audio_filepath)
    if file_metadata is None:
      continue

    if not full_scan:
      # stop at the first file that succeeds (for performance)
      # assume all directory files have the same artist/album couple
      r[file_metadata] = audio_filepaths
      break

    r[file_metadata].append(audio_filepath)

  return r


VALID_PATH_CHARS = frozenset(r"-_.()!#$%&'@^{}~" + string.ascii_letters + string.digits)


def sanitize_for_path(s):
  """ Sanitize a string to be FAT/NTFS friendly when used in file path. """
  s = s.translate(str.maketrans("/\\|*", "---x"))
  s = "".join(c for c in unidecode.unidecode_expect_ascii(s) if c in VALID_PATH_CHARS)
  s = s.strip()
  s = s.rstrip(".")  # this if for FAT on Android
  return s


def pattern_to_filepath(pattern, parent_dir, metadata):
  """ Build absolute cover file path from pattern. """
  assert(pattern != EMBEDDED_ALBUM_ART_SYMBOL)
  assert(metadata.artist is not None)
  assert(metadata.album is not None)
  filepath = pattern.format(artist=sanitize_for_path(metadata.artist),
                            album=sanitize_for_path(metadata.album))
  if not os.path.isabs(filepath):
    filepath = os.path.join(parent_dir, filepath)
  return filepath


def analyze_dir(stats, parent_dir, rel_filepaths, cover_pattern, *,
                ignore_existing=False, full_scan=False):
  """ Analyze a directory (non recursively) and return a list of Work objects. """
  r = []

  # filter out non audio files
  audio_filepaths = []
  for rel_filepath in rel_filepaths:
    stats["files"] += 1
    try:
      ext = os.path.splitext(rel_filepath)[1][1:].lower()
    except IndexError:
      continue
    if ext in AUDIO_EXTENSIONS:
      audio_filepaths.append(os.path.join(parent_dir, rel_filepath))

  # get metadata
  dir_metadata = get_dir_metadata(audio_filepaths, full_scan=full_scan)

  if audio_filepaths and (not dir_metadata):
    # failed to get any metadata for this directory
    stats["errors"] += 1
    logging.getLogger("sacad_r").error("Unable to read metadata for album directory '%s'" % (parent_dir))

  for metadata, album_audio_filepaths in dir_metadata.items():
    # update stats
    stats["albums"] += 1

    # add work item if needed
    if cover_pattern != EMBEDDED_ALBUM_ART_SYMBOL:
      cover_filepath = pattern_to_filepath(cover_pattern, parent_dir, metadata)
      missing = (not os.path.isfile(cover_filepath)) or ignore_existing
    else:
      cover_filepath = EMBEDDED_ALBUM_ART_SYMBOL
      missing = (not metadata.has_embedded_cover) or ignore_existing
    if missing:
      stats["missing covers"] += 1
      r.append(Work(cover_filepath, album_audio_filepaths, metadata))

  return r


def embed_album_art(cover_filepath, audio_filepaths):
  """ Embed album art into audio files. """
  with open(cover_filepath, "rb") as f:
    cover_data = f.read()

  for filepath in audio_filepaths:
    mf = mutagen.File(filepath)
    if (isinstance(mf.tags, mutagen._vorbis.VComment) or
            isinstance(mf, mutagen.ogg.OggFileType)):
      picture = mutagen.flac.Picture()
      picture.data = cover_data
      picture.type = mutagen.id3.PictureType.COVER_FRONT
      picture.mime = "image/jpeg"
      encoded_data = base64.b64encode(picture.write())
      mf["metadata_block_picture"] = encoded_data.decode("ascii")
    elif (isinstance(mf.tags, mutagen.id3.ID3) or
          isinstance(mf, mutagen.id3.ID3FileType)):
      mf.tags.add(mutagen.id3.APIC(mime="image/jpeg",
                                   type=mutagen.id3.PictureType.COVER_FRONT,
                                   data=cover_data))
    elif (isinstance(mf.tags, mutagen.mp4.MP4Tags) or
          isinstance(mf, mutagen.mp4.MP4)):
      mf["covr"] = [mutagen.mp4.MP4Cover(cover_data,
                                         imageformat=mutagen.mp4.AtomDataType.JPEG)]
    mf.save()


def ichunk(iterable, n):
  """ Split an iterable into n-sized chunks. """
  it = iter(iterable)
  while True:
    chunk = tuple(itertools.islice(it, n))
    if not chunk:
      return
    yield chunk


def get_covers(work, args):
  """ Get missing covers. """
  with contextlib.ExitStack() as cm:

    if args.cover_pattern == EMBEDDED_ALBUM_ART_SYMBOL:
      tmp_prefix = "%s_" % (os.path.splitext(os.path.basename(inspect.getfile(inspect.currentframe())))[0])
      tmp_dir = cm.enter_context(tempfile.TemporaryDirectory(prefix=tmp_prefix))

    # setup progress report
    stats = collections.OrderedDict(((k, 0) for k in("ok", "errors", "no result found")))
    progress = cm.enter_context(tqdm.tqdm(total=len(work),
                                          miniters=1,
                                          desc="Searching covers",
                                          unit="cover",
                                          postfix=stats))
    cm.enter_context(tqdm_logging.redirect_logging(progress))

    def post_download(future):
      work = futures[future]
      try:
        status = future.result()
      except Exception as exception:
        stats["errors"] += 1
        logging.getLogger("sacad_r").error("Error occured while searching %s: "
                                           "%s %s" % (work,
                                                      exception.__class__.__qualname__,
                                                      exception))
      else:
        if status:
          if work.cover_filepath == EMBEDDED_ALBUM_ART_SYMBOL:
            try:
              embed_album_art(work.tmp_cover_filepath, work.audio_filepaths)
            except Exception as exception:
              stats["errors"] += 1
              logging.getLogger("sacad_r").error("Error occured while embedding %s: "
                                                 "%s %s" % (work,
                                                            exception.__class__.__qualname__,
                                                            exception))
            else:
              stats["ok"] += 1
            finally:
              os.remove(work.tmp_cover_filepath)
          else:
            stats["ok"] += 1
        else:
          stats["no result found"] += 1
          logging.getLogger("sacad_r").warning("Unable to find %s" % (work))

      progress.set_postfix(stats, refresh=False)
      progress.update(1)

    # post work
    i = 0
    # default event loop on Windows has a 512 fd limit, see https://docs.python.org/3/library/asyncio-eventloops.html#windows
    # also on Linux default max open fd limit is 1024 (ulimit -n)
    # so work in smaller chunks to avoid hitting fd limit
    # this also updates the progress faster (instead of working on all searches, work on finishing the chunk before
    # getting to the next one)
    work_chunk_length = 16
    for work_chunk in ichunk(work, work_chunk_length):
      futures = {}
      for i, cur_work in enumerate(work_chunk, i):
        if cur_work.cover_filepath == EMBEDDED_ALBUM_ART_SYMBOL:
          cover_filepath = os.path.join(tmp_dir, "%00u.%s" % (i, args.format.name.lower()))
          cur_work.tmp_cover_filepath = cover_filepath
        else:
          cover_filepath = cur_work.cover_filepath
          os.makedirs(os.path.dirname(cover_filepath), exist_ok=True)
        coroutine = sacad.search_and_download(cur_work.metadata.album,
                                              cur_work.metadata.artist,
                                              args.format,
                                              args.size,
                                              cover_filepath,
                                              size_tolerance_prct=args.size_tolerance_prct,
                                              amazon_tlds=args.amazon_tlds,
                                              no_lq_sources=args.no_lq_sources)
        future = asyncio.ensure_future(coroutine)
        futures[future] = cur_work

      for future in futures:
        future.add_done_callback(post_download)

      # wait for end of work
      root_future = asyncio.gather(*futures.keys())
      asyncio.get_event_loop().run_until_complete(root_future)


def cl_main():
  # parse args
  arg_parser = argparse.ArgumentParser(description="SACAD (recursive tool) v%s.%s" % (sacad.__version__,
                                                                                      __doc__),
                                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
  arg_parser.add_argument("lib_dir",
                          help="Music library directory to recursively analyze")
  arg_parser.add_argument("size",
                          type=int,
                          help="Target image size")
  arg_parser.add_argument("cover_pattern",
                          help="""Cover image path pattern.
                                  {artist} and {album} are replaced by their tag value.
                                  You can set an absolute path, otherwise destination directory is relative to the audio files.
                                  Use single character '%s' to embed JPEG into audio files.""" % (EMBEDDED_ALBUM_ART_SYMBOL))
  arg_parser.add_argument("-i",
                          "--ignore-existing",
                          action="store_true",
                          default=False,
                          help="Ignore existing covers and force search and download for all files")
  arg_parser.add_argument("-f",
                          "--full-scan",
                          action="store_true",
                          default=False,
                          help="""Enable scanning of all audio files in each directory.
                                  By default the scanner will assume all audio files in a single directory are part of
                                  the same album, and only read metadata for the first file.
                                  Enable this if your files are organized in a way than allows files for different
                                  albums to be in the same directory level.
                                  WARNING: This will make the initial scan much slower.""")
  sacad.setup_common_args(arg_parser)
  arg_parser.add_argument("-v",
                          "--verbose",
                          action="store_true",
                          default=False,
                          dest="verbose",
                          help="Enable verbose output")
  args = arg_parser.parse_args()
  if args.cover_pattern == EMBEDDED_ALBUM_ART_SYMBOL:
    args.format = "jpg"
  else:
    args.format = os.path.splitext(args.cover_pattern)[1][1:].lower()
  try:
    args.format = sacad.SUPPORTED_IMG_FORMATS[args.format]
  except KeyError:
    print("Unable to guess image format from extension, or unknown format: %s" % (args.format))
    exit(1)

  # setup logger
  if not args.verbose:
    logging.getLogger("sacad_r").setLevel(logging.WARNING)
    logging.getLogger().setLevel(logging.ERROR)
    logging.getLogger("asyncio").setLevel(logging.CRITICAL + 1)
    fmt = "%(name)s: %(message)s"
  else:
    logging.getLogger("sacad_r").setLevel(logging.DEBUG)
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    fmt = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
  logging_formatter = colored_logging.ColoredFormatter(fmt=fmt)
  logging_handler = logging.StreamHandler()
  logging_handler.setFormatter(logging_formatter)
  logging.getLogger().addHandler(logging_handler)

  # do the job
  work = analyze_lib(args.lib_dir,
                     args.cover_pattern,
                     ignore_existing=args.ignore_existing,
                     full_scan=args.full_scan)
  get_covers(work, args)


if __name__ == "__main__":
  cl_main()
