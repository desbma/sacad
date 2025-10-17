# SACAD

## Smart Automatic Cover Art Downloader

[![AUR version](https://img.shields.io/aur/version/sacad.svg?style=flat)](https://aur.archlinux.org/packages/sacad/)
[![CI status](https://img.shields.io/github/actions/workflow/status/desbma/sacad/ci.yml)](https://github.com/desbma/sacad/actions)
[![License](https://img.shields.io/github/license/desbma/sacad.svg?style=flat)](https://github.com/desbma/sacad/blob/master/LICENSE)

---

Since version 3.0, this tool has been completely rewritten in Rust.

The previous Python version can be found in the [2.x branch](https://github.com/desbma/sacad/tree/2.x).

---

SACAD is a multi platform command line tool to download album covers without manual intervention, ideal for integration in scripts, audio players, etc.

SACAD also provides a second command line tool, `sacad_r`, to scan a music library, read metadata from audio tags, and download missing covers automatically, optionally embedding the image into audio audio files.

## Features

- Can target specific image size, and find results for high resolution covers
- Support JPEG and PNG formats
- Customizable output: save image along with the audio files / in a different directory named by artist/album / embed cover in audio files...
- Currently support the following cover sources:
  - CoverArtArchive (MusicBrainz)
  - Deezer
  - Discogs
  - Last.fm
  - Itunes
- Smart sorting algorithm to select THE best cover for a given query, using several factors: source reliability, image format, image size, image similarity with reference cover, etc.
- Automatically crunch PNG images (can save 30% of file size without any loss of quality)
- Cache search data locally for faster future search
- Automatically convert/resize image if needed
- Multi platform (Windows/Mac/Linux)

## Installation

### From source

You need a Rust build environment for example from [rustup](https://rustup.rs/).

Run in the current repository:

```bash
cargo install --path .
```

### From [`crates.io`](https://crates.io/)

```bash
cargo install sacad
```

## Command line usage

Two tools are provided: `sacad` to search and download one cover, and `sacad_r` to scan a music library and download all missing covers.

Run `sacad -h` / `sacad_r -h` to get full command line reference.

### Examples

To download the cover of _Master of Puppets_ from _Metallica_, to the file `AlbumArt.jpg`, targeting ~ 600x600 pixel resolution:

```bash
sacad "metallica" "master of puppets" 600 AlbumArt.jpg
```

To download covers for your library with the same parameters as previous example:

```bash
sacad_r library_directory 600 AlbumArt.jpg
```

## License

[Mozilla Public License Version 2.0](https://www.mozilla.org/MPL/2.0/)
