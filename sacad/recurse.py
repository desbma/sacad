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
import sys
import tempfile

import mutagen
import tqdm

import sacad


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


def analyze_lib(lib_dir, cover_filename):
  """ Recursively analyze library, and return a dict of path -> (artist, album). """
  work = {}
  stats = collections.OrderedDict(((k, 0) for k in("files", "albums", "missing covers", "errors")))
  failed_dirs = []
  with tqdm.tqdm(desc="Analyzing library",
                 unit=" dirs",
                 postfix=stats) as progress:
    for rootpath, rel_dirpaths, rel_filepaths in os.walk(lib_dir):
      metadata = analyze_dir(stats,
                             rootpath,
                             rel_filepaths,
                             cover_filename,
                             failed_dirs)
      progress.set_postfix(stats)
      progress.update(1)
      if all(metadata[:-1]):
        work[rootpath] = metadata[:-1]
  for failed_dir in failed_dirs:
    print("Unable to read metadata for album directory '%s'" % (failed_dir))
  return work


def get_metadata(audio_filepaths):
  """ Return a tuple of album, artist, has_embedded_album_art from a list of audio files. """
  artist, album, has_embedded_album_art = None, None, None
  for audio_filepath in audio_filepaths:
    try:
      mf = mutagen.File(audio_filepath)
    except Exception:
      continue
    if mf is None:
      continue

    # artist
    for key in ("albumartist", "artist",  # ogg
                "TPE1", "TPE2",  # mp3
                "aART", "\xa9ART"):  # mp4
      try:
        val = mf.get(key, None)
      except ValueError:
        val = None
      if val is not None:
        artist = val[0]
        break

    # album
    for key in ("_album", "album",  # ogg
                "TALB",  # mp3
                "\xa9alb"):  # mp4
      try:
        val = mf.get(key, None)
      except ValueError:
        val = None
      if val is not None:
        album = val[0]
        break

    if artist and album:
      # album art
      if isinstance(mf, mutagen.ogg.OggFileType):
        has_embedded_album_art = "metadata_block_picture" in mf
      elif isinstance(mf, mutagen.mp3.MP3):
        has_embedded_album_art = any(map(operator.methodcaller("startswith", "APIC:"), mf.keys()))
      elif isinstance(mf, mutagen.mp4.MP4):
        has_embedded_album_art = "covr" in mf

      # stop at the first file that succeeds (for performance)
      break

  return artist, album, has_embedded_album_art


def analyze_dir(stats, parent_dir, rel_filepaths, cover_filename, failed_dirs):
  """ Analyze a directory (non recursively) to get its album metadata if it is one. """
  no_metadata = None, None, None
  metadata = no_metadata
  audio_filepaths = []
  for rel_filepath in rel_filepaths:
    stats["files"] += 1
    try:
      ext = os.path.splitext(rel_filepath)[1][1:].lower()
    except IndexError:
      continue
    if ext in AUDIO_EXTENSIONS:
      audio_filepaths.append(os.path.join(parent_dir, rel_filepath))
  if audio_filepaths:
    stats["albums"] += 1
    if (cover_filename != EMBEDDED_ALBUM_ART_SYMBOL):
      missing = not os.path.isfile(os.path.join(parent_dir, cover_filename))
      if missing:
        metadata = get_metadata(audio_filepaths)
    else:
      metadata = get_metadata(audio_filepaths)
      missing = not metadata[2]
    if missing:
      stats["missing covers"] += 1
      if not all(metadata[:-1]):
        # failed to get metadata for this album
        stats["errors"] += 1
        failed_dirs.append(parent_dir)
    else:
      metadata = no_metadata
  return metadata


def embed_album_art(cover_filepath, path):
  """ Embed album art into audio files. """
  with open(cover_filepath, "rb") as f:
    cover_data = f.read()

  for filename in os.listdir(path):
    try:
      ext = os.path.splitext(filename)[1][1:].lower()
    except IndexError:
      continue

    if ext in AUDIO_EXTENSIONS:
      filepath = os.path.join(path, filename)
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

    if args.filename == EMBEDDED_ALBUM_ART_SYMBOL:
      tmp_prefix = "%s_" % (os.path.splitext(os.path.basename(inspect.getfile(inspect.currentframe())))[0])
      tmp_dir = cm.enter_context(tempfile.TemporaryDirectory(prefix=tmp_prefix))

    # setup progress report
    stats = collections.OrderedDict(((k, 0) for k in("ok", "errors", "no result found")))
    errors = []
    not_found = []
    with tqdm.tqdm(total=len(work),
                   miniters=1,
                   desc="Searching covers",
                   unit=" covers",
                   postfix=stats) as progress:

      def update_progress(future):
        path, cover_filepath, artist, album = futures[future]
        try:
          status = future.result()
        except Exception as exception:
          stats["errors"] += 1
          errors.append((path, artist, album, exception))
        else:
          if status:
            if args.filename == EMBEDDED_ALBUM_ART_SYMBOL:
              try:
                embed_album_art(cover_filepath, path)
              except Exception as exception:
                stats["errors"] += 1
                errors.append((path, artist, album, exception))
              else:
                stats["ok"] += 1
              finally:
                os.remove(cover_filepath)
            else:
              stats["ok"] += 1
          else:
            stats["no result found"] += 1
            not_found.append((path, artist, album))
        progress.set_postfix(stats)
        progress.update(1)

      # post work
      async_loop = asyncio.get_event_loop()
      i = 0
      if sacad.ENABLE_ASYNCIO_LOW_FD_LIMIT_WORKAROUND:
        # work in smaller chunks to avoid hitting fd limit
        work_chunk_length = 16
      else:
        work_chunk_length = sys.maxsize
      for work_chunk in ichunk(work.items(), work_chunk_length):
        futures = {}
        for i, (path, (artist, album)) in enumerate(work_chunk, i):
          if args.filename == EMBEDDED_ALBUM_ART_SYMBOL:
            cover_filepath = os.path.join(tmp_dir, "%00u.%s" % (i, args.format.name.lower()))
          else:
            cover_filepath = os.path.join(path, args.filename)
          coroutine = sacad.search_and_download(album,
                                                artist,
                                                args.format,
                                                args.size,
                                                cover_filepath,
                                                size_tolerance_prct=args.size_tolerance_prct,
                                                amazon_tlds=args.amazon_tlds,
                                                no_lq_sources=args.no_lq_sources,
                                                async_loop=async_loop)
          try:
            # python >= 3.4.4
            future = asyncio.ensure_future(coroutine, loop=async_loop)
          except AttributeError:
            # python < 3.4.4
            future = asyncio.async(coroutine, loop=async_loop)
          futures[future] = (path, cover_filepath, artist, album)

        for future in futures:
          future.add_done_callback(update_progress)

        # wait for end of work
        root_future = asyncio.gather(*futures.keys(), loop=async_loop)
        async_loop.run_until_complete(root_future)

  # report accumulated errors
  for path, artist, album in not_found:
    print("Unable to find cover for '%s' by '%s' from '%s'" % (album, artist, path))
  for path, artist, album, exception in errors:
    print("Error occured while handling cover for '%s' by '%s' from '%s': %s %s" % (album,
                                                                                    artist,
                                                                                    path,
                                                                                    exception.__class__.__qualname__,
                                                                                    exception))
  if errors:
    print("Please report this at https://github.com/desbma/sacad/issues")


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
  arg_parser.add_argument("filename",
                          help="Cover image filename ('%s' to embed JPEG into audio files)" % (EMBEDDED_ALBUM_ART_SYMBOL))
  sacad.setup_common_args(arg_parser)
  args = arg_parser.parse_args()
  if args.filename == EMBEDDED_ALBUM_ART_SYMBOL:
    args.format = "jpg"
  else:
    args.format = os.path.splitext(args.filename)[1][1:].lower()
  try:
    args.format = sacad.SUPPORTED_IMG_FORMATS[args.format]
  except KeyError:
    print("Unable to guess image format from extension, or unknown format: %s" % (args.format))
    exit(1)

  # silence the logger
  logging.basicConfig(format="%(asctime)s %(process)d %(threadName)s: %(message)s", level=logging.ERROR)

  # do the job
  work = analyze_lib(args.lib_dir, args.filename)
  get_covers(work, args)


if __name__ == "__main__":
  cl_main()
