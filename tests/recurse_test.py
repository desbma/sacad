#!/usr/bin/env python3

""" Unit tests for recurse module. """

import collections
import contextlib
import functools
import os
import shutil
import tempfile
import unittest
import urllib.parse

import mutagen
import requests

import sacad.recurse as recurse
from sacad.recurse import Metadata


def download(url, filepath):
    """Download URL to a local file."""
    cache_dir = os.getenv("TEST_DL_CACHE_DIR")
    if cache_dir is not None:
        os.makedirs(cache_dir, exist_ok=True)
        cache_filepath = os.path.join(cache_dir, os.path.basename(urllib.parse.urlsplit(url).path))
        if os.path.isfile(cache_filepath):
            shutil.copyfile(cache_filepath, filepath)
            return
    with contextlib.closing(
        requests.get(url, stream=True, headers={"User-Agent": "Mozilla/5.0 (nope) Gecko/20100101 Firefox/90.0"})
    ) as response:
        response.raise_for_status()
        with open(filepath, "wb") as f:
            for chunk in response.iter_content(2 ** 14):
                f.write(chunk)
    if cache_dir is not None:
        shutil.copyfile(filepath, cache_filepath)


class TestRecursive(unittest.TestCase):

    """Test suite for recurse module."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.maxDiff = None

    @classmethod
    def setUpClass(cls):
        """Set up test suite stuff."""
        #
        # Album 1: 1 valid ogg track
        #

        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.album1_dir = os.path.join(cls.temp_dir.name, "album1")
        os.mkdir(cls.album1_dir)
        url = "https://www.dropbox.com/s/5xr61miqznv06sx/ACDC_-_Back_In_Black-sample.ogg?dl=1"
        cls.album1_filepath = os.path.join(cls.album1_dir, "2 track.ogg")
        download(url, cls.album1_filepath)
        mf = mutagen.File(cls.album1_filepath)
        mf["artist"] = "ARTIST1"
        mf["album"] = "ALBUM1"
        mf.save()

        #
        # Album 2: 1 valid track + 1 invalid file + 1 png file
        #

        cls.album2_dir = os.path.join(cls.temp_dir.name, "album2")
        os.mkdir(cls.album2_dir)
        cls.album2_filepath1 = os.path.join(cls.album2_dir, "1.dat")
        with open(cls.album2_filepath1, "wb") as f:
            f.write(b"\x00" * 8)

        cls.album2_filepath2 = shutil.copyfile(cls.album1_filepath, os.path.join(cls.album2_dir, "2 track.ogg"))
        mf = mutagen.File(cls.album2_filepath2)
        mf["artist"] = "ARTIST2"
        mf["album"] = "ALBUM2"
        mf.save()

        open(os.path.join(cls.album2_dir, "1.png"), "wb").close()

        #
        # Album 3: 1 valid mp3 track
        #

        cls.album3_dir = os.path.join(cls.temp_dir.name, "album3")
        os.mkdir(cls.album3_dir)
        url = r"https://www.dropbox.com/s/mtac0y8azs5hqxo/Shuffle%2520for%2520K.M.mp3?dl=1"
        cls.album3_filepath = os.path.join(cls.album3_dir, "1 track.mp3")
        download(url, cls.album3_filepath)

        #
        # Album 4: 1 valid m4a track
        #

        cls.album4_dir = os.path.join(cls.temp_dir.name, "album4")
        os.mkdir(cls.album4_dir)
        url = "https://auphonic.com/media/audio-examples/01.auphonic-demo-unprocessed.m4a"
        cls.album4_filepath = os.path.join(cls.album4_dir, "1 track.m4a")
        download(url, cls.album4_filepath)

        #
        # Album 5: 2 valid ogg tracks with different metadata
        #

        cls.album5_dir = os.path.join(cls.temp_dir.name, "album5")
        os.mkdir(cls.album5_dir)
        cls.album5_filepath1 = shutil.copy(cls.album1_filepath, cls.album5_dir)
        cls.album5_filepath2 = shutil.copy(cls.album2_filepath2, os.path.join(cls.album5_dir, "bzz.ogg"))

        #
        # 'not album' dir: 1 invalid file
        #

        cls.not_album_dir = os.path.join(cls.temp_dir.name, "not an album")
        os.mkdir(cls.not_album_dir)
        shutil.copyfile(cls.album2_filepath1, os.path.join(cls.not_album_dir, "a.dat"))

        #
        # 'invalid album' dir: 1 ogg track without metadata + 1 invalid file
        #

        cls.invalid_album_dir = os.path.join(cls.temp_dir.name, "invalid album")
        os.mkdir(cls.invalid_album_dir)
        cls.invalid_album_filepath1 = shutil.copyfile(
            cls.album1_filepath, os.path.join(cls.invalid_album_dir, "3 track.ogg")
        )
        mf = mutagen.File(cls.invalid_album_filepath1)
        del mf["album"]
        mf.save()
        cls.invalid_album_filepath2 = shutil.copyfile(
            cls.album2_filepath1, os.path.join(cls.invalid_album_dir, "2 track.ogg")
        )

    @classmethod
    def tearDownClass(cls):
        """Cleanup test suite stuff."""
        cls.temp_dir.cleanup()

    def test_analyze_lib(self):
        """Test recursive directory analysis."""
        for full_scan in (False, True):
            for all_formats in (False, True):
                with self.subTest(full_scan=full_scan, all_formats=all_formats):
                    work = recurse.analyze_lib(
                        __class__.temp_dir.name, "a.jpg", full_scan=full_scan, all_formats=all_formats
                    )
                    work.sort(key=lambda x: (x.cover_filepath, x.metadata))
                    self.assertEqual(len(work), 5 + int(full_scan))
                    self.assertEqual(work[0].cover_filepath, os.path.join(__class__.album1_dir, "a.jpg"))
                    self.assertEqual(work[0].metadata, Metadata("ARTIST1", "ALBUM1", False))
                    self.assertEqual(work[1].cover_filepath, os.path.join(__class__.album2_dir, "a.jpg"))
                    self.assertEqual(work[1].metadata, Metadata("ARTIST2", "ALBUM2", False))
                    self.assertEqual(work[2].cover_filepath, os.path.join(__class__.album3_dir, "a.jpg"))
                    self.assertEqual(work[2].metadata, Metadata("jpfmband", "Paris S.F", True))
                    self.assertEqual(work[3].cover_filepath, os.path.join(__class__.album4_dir, "a.jpg"))
                    self.assertEqual(work[3].metadata, Metadata("Auphonic", "Auphonic Demonstration", True))
                    self.assertEqual(work[4].cover_filepath, os.path.join(__class__.album5_dir, "a.jpg"))
                    self.assertEqual(work[4].metadata, Metadata("ARTIST1", "ALBUM1", False))
                    if full_scan:
                        self.assertEqual(work[5].cover_filepath, os.path.join(__class__.album5_dir, "a.jpg"))
                        self.assertEqual(work[5].metadata, Metadata("ARTIST2", "ALBUM2", False))

                    work = recurse.analyze_lib(
                        __class__.temp_dir.name, "1.dat", full_scan=full_scan, all_formats=all_formats
                    )
                    work.sort(key=lambda x: (x.cover_filepath, x.metadata))
                    self.assertEqual(len(work), 4 + int(full_scan) - int(all_formats))
                    idx = 0
                    if not all_formats:
                        self.assertEqual(work[idx].cover_filepath, os.path.join(__class__.album1_dir, "1.dat"))
                        self.assertEqual(work[idx].metadata, Metadata("ARTIST1", "ALBUM1", False))
                        idx += 1
                    self.assertEqual(work[idx].cover_filepath, os.path.join(__class__.album3_dir, "1.dat"))
                    self.assertEqual(work[idx].metadata, Metadata("jpfmband", "Paris S.F", True))
                    idx += 1
                    self.assertEqual(work[idx].cover_filepath, os.path.join(__class__.album4_dir, "1.dat"))
                    self.assertEqual(work[idx].metadata, Metadata("Auphonic", "Auphonic Demonstration", True))
                    idx += 1
                    self.assertEqual(work[idx].cover_filepath, os.path.join(__class__.album5_dir, "1.dat"))
                    self.assertEqual(work[idx].metadata, Metadata("ARTIST1", "ALBUM1", False))
                    idx += 1
                    if full_scan:
                        self.assertEqual(work[idx].cover_filepath, os.path.join(__class__.album5_dir, "1.dat"))
                        self.assertEqual(work[idx].metadata, Metadata("ARTIST2", "ALBUM2", False))

    def test_get_file_metadata(self):
        """Test file metadata extraction."""
        self.assertEqual(recurse.get_file_metadata(__class__.album1_filepath), Metadata("ARTIST1", "ALBUM1", False))
        self.assertIsNone(recurse.get_file_metadata(__class__.album2_filepath1))
        self.assertEqual(recurse.get_file_metadata(__class__.album2_filepath2), Metadata("ARTIST2", "ALBUM2", False))
        self.assertIsNone(recurse.get_file_metadata(__class__.invalid_album_filepath1))
        self.assertIsNone(recurse.get_file_metadata(__class__.invalid_album_filepath2))

    def test_get_dir_metadata(self):
        """Test directory metadata extraction."""
        self.assertEqual(
            dict(recurse.get_dir_metadata((__class__.album1_filepath,))),
            {Metadata("ARTIST1", "ALBUM1", False): (__class__.album1_filepath,)},
        )

        self.assertEqual(
            dict(recurse.get_dir_metadata((__class__.album2_filepath1, __class__.album2_filepath2))),
            {Metadata("ARTIST2", "ALBUM2", False): (__class__.album2_filepath1, __class__.album2_filepath2)},
        )

        self.assertEqual(
            dict(recurse.get_dir_metadata((__class__.album3_filepath,))),
            {Metadata("jpfmband", "Paris S.F", True): (__class__.album3_filepath,)},
        )

        self.assertEqual(
            dict(recurse.get_dir_metadata((__class__.album4_filepath,))),
            {Metadata("Auphonic", "Auphonic Demonstration", True): (__class__.album4_filepath,)},
        )

        self.assertEqual(
            dict(recurse.get_dir_metadata((__class__.album5_filepath1, __class__.album5_filepath2))),
            {Metadata("ARTIST1", "ALBUM1", False): (__class__.album5_filepath1, __class__.album5_filepath2)},
        )

        self.assertEqual(
            dict(recurse.get_dir_metadata((__class__.album5_filepath1, __class__.album5_filepath2), full_scan=True)),
            {
                Metadata("ARTIST1", "ALBUM1", False): [__class__.album5_filepath1],
                Metadata("ARTIST2", "ALBUM2", False): [__class__.album5_filepath2],
            },
        )

        r = recurse.get_dir_metadata(
            map(functools.partial(os.path.join, __class__.not_album_dir), os.listdir(__class__.not_album_dir))
        )
        self.assertEqual(len(r), 0)

        r = recurse.get_dir_metadata(
            map(functools.partial(os.path.join, __class__.invalid_album_dir), os.listdir(__class__.invalid_album_dir))
        )
        self.assertEqual(len(r), 0)

    def test_analyze_dir(self):
        """Test directory analysis and reporting."""
        stats = collections.defaultdict(int)
        r = recurse.analyze_dir(stats, __class__.album1_dir, os.listdir(__class__.album1_dir), "1.jpg")
        self.assertIn("files", stats)
        self.assertEqual(stats["files"], 1)
        self.assertIn("albums", stats)
        self.assertEqual(stats["albums"], 1)
        self.assertIn("missing covers", stats)
        self.assertEqual(stats["missing covers"], 1)
        self.assertNotIn("errors", stats)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0].cover_filepath, os.path.join(__class__.album1_dir, "1.jpg"))
        self.assertEqual(r[0].audio_filepaths, (__class__.album1_filepath,))
        self.assertEqual(r[0].metadata, Metadata("ARTIST1", "ALBUM1", False))

        for all_formats in (False, True):
            for format_ext in ("jpg", "jpeg"):
                with self.subTest(all_formats=all_formats, format_ext=format_ext):
                    stats.clear()
                    r = recurse.analyze_dir(
                        stats,
                        __class__.album2_dir,
                        os.listdir(__class__.album2_dir),
                        f"1.{format_ext}",
                        all_formats=all_formats,
                    )
                    self.assertIn("files", stats)
                    self.assertEqual(stats["files"], 3)
                    self.assertIn("albums", stats)
                    self.assertEqual(stats["albums"], 1)
                    if all_formats:
                        self.assertNotIn("missing covers", stats)
                        self.assertEqual(len(r), 0)
                    else:
                        self.assertIn("missing covers", stats)
                        self.assertEqual(stats["missing covers"], 1)
                        self.assertEqual(len(r), 1)
                        self.assertEqual(r[0].cover_filepath, os.path.join(__class__.album2_dir, f"1.{format_ext}"))
                        self.assertEqual(r[0].audio_filepaths, (__class__.album2_filepath2,))
                        self.assertEqual(r[0].metadata, Metadata("ARTIST2", "ALBUM2", False))
                    self.assertNotIn("errors", stats)

            stats.clear()
            r = recurse.analyze_dir(stats, __class__.album2_dir, os.listdir(__class__.album2_dir), "1.dat")
            self.assertIn("files", stats)
            self.assertEqual(stats["files"], 3)
            self.assertIn("albums", stats)
            self.assertEqual(stats["albums"], 1)
            self.assertNotIn("missing covers", stats)
            self.assertNotIn("errors", stats)
            self.assertEqual(len(r), 0)

            stats.clear()
            r = recurse.analyze_dir(stats, __class__.not_album_dir, os.listdir(__class__.not_album_dir), "1.jpg")
            self.assertIn("files", stats)
            self.assertEqual(stats["files"], 1)
            self.assertNotIn("albums", stats)
            self.assertNotIn("missing covers", stats)
            self.assertNotIn("errors", stats)
            self.assertEqual(len(r), 0)

            stats.clear()
            r = recurse.analyze_dir(
                stats, __class__.invalid_album_dir, os.listdir(__class__.invalid_album_dir), "1.jpg"
            )
            self.assertIn("files", stats)
            self.assertEqual(stats["files"], 2)
            self.assertIn("errors", stats)
            self.assertEqual(stats["errors"], 1)
            self.assertEqual(len(r), 0)

            open(os.path.join(__class__.album1_dir, "1.jpg"), "wb").close()
            for ignore_existing in (False, True):
                with self.subTest(ignore_existing=ignore_existing):
                    stats.clear()
                    r = recurse.analyze_dir(
                        stats,
                        __class__.album1_dir,
                        os.listdir(__class__.album1_dir),
                        "1.jpg",
                        ignore_existing=ignore_existing,
                    )
                    self.assertIn("files", stats)
                    self.assertEqual(stats["files"], 2)
                    self.assertIn("albums", stats)
                    self.assertEqual(stats["albums"], 1)
                    if not ignore_existing:
                        self.assertNotIn("missing covers", stats)
                        self.assertEqual(len(r), 0)
                    else:
                        self.assertIn("missing covers", stats)
                        self.assertEqual(stats["missing covers"], 1)
                        self.assertEqual(len(r), 1)
                        self.assertEqual(r[0].cover_filepath, os.path.join(__class__.album1_dir, "1.jpg"))
                        self.assertEqual(r[0].audio_filepaths, (__class__.album1_filepath,))
                        self.assertEqual(r[0].metadata, Metadata("ARTIST1", "ALBUM1", False))
                    self.assertNotIn("errors", stats)

    def test_pattern_to_filepath(self):
        """Test filepath generation from pattern."""
        tmp_dir = tempfile.gettempdir()
        metadata = Metadata("art1st|*\\//", "albvm|*\\//", None)
        self.assertEqual(recurse.pattern_to_filepath("a", tmp_dir, metadata), os.path.join(tmp_dir, "a"))
        self.assertEqual(
            recurse.pattern_to_filepath("{artist}_a", tmp_dir, metadata), os.path.join(tmp_dir, "art1st-x---_a")
        )
        self.assertEqual(
            recurse.pattern_to_filepath("{album}_a", tmp_dir, metadata), os.path.join(tmp_dir, "albvm-x---_a")
        )
        self.assertEqual(
            recurse.pattern_to_filepath("{artist}_{album}_a", tmp_dir, metadata),
            os.path.join(tmp_dir, "art1st-x---_albvm-x---_a"),
        )
        self.assertEqual(
            recurse.pattern_to_filepath(os.path.join("{artist}", "{album}", "a"), tmp_dir, metadata),
            os.path.join(tmp_dir, "art1st-x---", "albvm-x---", "a"),
        )
        self.assertEqual(
            recurse.pattern_to_filepath(os.path.join(tmp_dir, "d", "{artist}", "{album}", "a"), tmp_dir, metadata),
            os.path.join(tmp_dir, "d", "art1st-x---", "albvm-x---", "a"),
        )


if __name__ == "__main__":
    # run tests
    unittest.main()
