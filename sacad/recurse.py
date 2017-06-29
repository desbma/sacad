#!/usr/bin/env python3

""" Recursively search and download album covers for a music library. """

import argparse
import collections
import concurrent.futures
import logging
import multiprocessing
import os
import shutil
import sys

import mutagen
import tqdm

import sacad


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
      if all(metadata):
        work[rootpath] = metadata
  for failed_dir in failed_dirs:
    print("Unable to read metadata for album directory '%s'" % (failed_dir))
  return work


def get_metadata(audio_filepaths):
  """ Return a tuple of album, artist from a list of audio files. """
  artist, album = None, None
  for audio_filepath in audio_filepaths:
    try:
      mf = mutagen.File(audio_filepath)
    except Exception:
      continue
    if mf is None:
      continue
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
      # stop at the first file that succeeds (for performance)
      break
  return artist, album


def analyze_dir(stats, parent_dir, rel_filepaths, cover_filename, failed_dirs):
  """ Analyze a directory (non recursively) to get its album metadata if it is one. """
  metadata = None, None
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
    if not os.path.isfile(os.path.join(parent_dir, cover_filename)):
      stats["missing covers"] += 1
      metadata = get_metadata(audio_filepaths)
      if not all(metadata):
        # failed to get metadata for this album
        stats["errors"] += 1
        failed_dirs.append(parent_dir)
  return metadata


def get_covers(work, args):
  """ Get missing covers. """
  with concurrent.futures.ProcessPoolExecutor(max_workers=min(1,  # TODO fix deadlock
                                                              multiprocessing.cpu_count())) as executor:
    # post work
    futures = {}
    for path, (artist, album) in work.items():
      future = executor.submit(sacad.search_and_download,
                               album,
                               artist,
                               args.format,
                               args.size,
                               args.size_tolerance_prct,
                               args.amazon_tlds,
                               args.no_lq_sources,
                               os.path.join(path, args.filename),
                               process_parallelism=True)
      futures[future] = (path, artist, album)

    # follow progress
    stats = collections.OrderedDict(((k, 0) for k in("ok", "errors", "no result found")))
    errors = []
    not_found = []
    with tqdm.tqdm(concurrent.futures.as_completed(futures),
                   total=len(futures),
                   miniters=1,
                   desc="Searching covers",
                   unit=" covers",
                   postfix=stats) as progress:
      for i, future in enumerate(progress, 1):
        path, artist, album = futures[future]
        try:
          status = future.result()
        except Exception as exception:
          stats["errors"] += 1
          errors.append((path, artist, album, exception))
        else:
          if status:
            stats["ok"] += 1
          else:
            stats["no result found"] += 1
            not_found.append((path, artist, album))
        progress.set_postfix(stats)

  for path, artist, album in not_found:
    print("Unable to find cover for '%s' by '%s' from '%s'" % (album, artist, path))
  for path, artist, album, exception in errors:
    print("Error occured while searching cover for '%s' by '%s' from '%s': %s %s" % (album,
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
                          help="Cover image filename")
  sacad.setup_common_args(arg_parser)
  args = arg_parser.parse_args()
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
