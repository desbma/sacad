#!/usr/bin/env python3

""" Recursively search and download album covers for a music library. """

import argparse
import collections
import itertools
import os
import time

import mutagen

import sacad


AUDIO_EXTENSIONS = ("aac",
                    "ape",
                    "flac",
                    "m4a",
                    "mp3",
                    "mp4",
                    "ogg",
                    "oga",
                    "opus",
                    "wv")


def analyze_lib(lib_dir, cover_filename):
  """ Recursively analyze library, and return a dict of path -> (artist, album). """
  work = collections.OrderedDict()
  scrobbler = itertools.cycle("|/-\\")
  stats = collections.OrderedDict(((k, 0) for k in("dirs", "files", "albums", "missing covers", "errors")))
  time_progress_shown = show_analyze_progress(stats, scrobbler)
  for rootpath, rel_dirpaths, rel_filepaths in os.walk(lib_dir):
    stats["dirs"] += 1
    metadata, time_progress_shown = analyze_dir(stats, rootpath, rel_filepaths, cover_filename, scrobbler, time_progress_shown)
    if all(metadata):
      work[rootpath] = metadata
  show_analyze_progress(stats, scrobbler, end=True)
  return work


def get_metadata(audio_filepaths):
  """ Return a tuple of album, artist from a list of audio files. """
  artist, album = None, None
  for audio_filepath in audio_filepaths:
    mf = mutagen.File(audio_filepath)
    if mf is None:
      continue
    artist = mf.get("artist", None)
    album = mf.get("album", None)
    # TODO error handling
    # TODO handle album artist
    break  # consider the first file that succeeds for performance
  return artist, album


def analyze_dir(stats, parent_dir, rel_filepaths, cover_filename, scrobbler, time_progress_shown):
  """ Analyze a directory (non recursively) to get its album metadata if it is one. """
  metadata = None, None
  audio_filepaths = []
  for rel_filepath in rel_filepaths:
    stats["files"] += 1
    time_progress_shown = show_analyze_progress(stats, scrobbler, time_progress_shown=time_progress_shown)
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
  return metadata, time_progress_shown


def show_analyze_progress(stats, scrobbler, *, time_progress_shown=0, end=False):
  """ Display analysis global progress. """
  now = time.time()
  if end or (now - time_progress_shown > 0.1):  # do not refresh display at each call for performance
    time_progress_shown = now
    print("Analyzing library %s | %s" % (next(scrobbler) if not end else "-",
                                         "  ".join(("%u %s" % (v, k)) for k, v in stats.items())),
          end="\r" if not end else "\n")
  return time_progress_shown


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

  # run
  analyze_lib(args.lib_dir, args.filename)
