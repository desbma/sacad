# SACAD

## Smart Automatic Cover Art Downloader

[![PyPI version](https://img.shields.io/pypi/v/sacad.svg?style=flat)](https://pypi.python.org/pypi/sacad/)
[![AUR version](https://img.shields.io/aur/version/sacad.svg?style=flat)](https://aur.archlinux.org/packages/sacad/)
[![Tests status](https://github.com/desbma/sacad/actions/workflows/ci.yml/badge.svg)](https://github.com/desbma/sacad/actions)
[![Coverage](https://img.shields.io/coveralls/desbma/sacad/master.svg?style=flat)](https://coveralls.io/github/desbma/sacad?branch=master)
[![Lines of code](https://tokei.rs/b1/github/desbma/sacad)](https://github.com/desbma/sacad)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/sacad.svg?style=flat)](https://pypi.python.org/pypi/sacad/)
[![License](https://img.shields.io/github/license/desbma/sacad.svg?style=flat)](https://github.com/desbma/sacad/blob/master/LICENSE)

SACAD is a multi platform command line tool to download album covers without manual intervention, ideal for integration in scripts, audio players, etc.

SACAD also provides a second command line tool, `sacad_r`, to scan a music library, read metadata from audio tags, and download missing covers automatically, optionally embedding the image into audio audio files.

## Features

- Can target specific image size, and find results for high resolution covers
- Support JPEG and PNG formats
- Customizable output: save image along with the audio files / in a different directory named by artist/album / embed cover in audio files...
- Currently support the following cover sources:
  - Amazon CD (.com, .ca, .cn, .fr, .de, .co.jp and .co.uk variants)
  - Amazon digital music
  - ~~CoverLib~~ (site is dead)
  - Deezer
  - Discogs
  - ~~Google Images~~ (removed, too unreliable)
  - Last.fm
  - Itunes
- Smart sorting algorithm to select THE best cover for a given query, using several factors: source reliability, image format, image size, image similarity with reference cover, etc.
- Automatically crunch images with optipng or jpegoptim (can save 30% of filesize without any loss of quality, great for portable players)
- Cache search results locally for faster future search
- Do everything to avoid getting blocked by the sources: hide user-agent and automatically take care of rate limiting
- Automatically convert/resize image if needed
- Multiplatform (Windows/Mac/Linux)

SACAD is designed to be robust and be executed in batch of thousands of queries:

- HTML parsing is done without regex but with the LXML library, which is faster, and more robust to page changes
- When the size of an image reported by a source is not reliable (ie. Google Images), automatically download the first KB of the file to get its real size from the file header
- Process several queries simultaneously (using [asyncio](https://docs.python.org/3/library/asyncio.html)), to speed up processing
- Automatically reuse TCP connections (HTTP Keep-Alive), for better network performance
- Automatically retry failed HTTP requests
- Music library scan supports all common audio formats (MP3, AAC, Vorbis, FLAC..)
- Cover sources page or API changes are quickly detected, thanks to high test coverage, and SACAD is quickly updated accordingly

## Installation

SACAD requires [Python](https://www.python.org/downloads/) >= 3.7.

### Standalone Windows executable

Windows users can download a [standalone binary](https://github.com/desbma/sacad/releases/latest) which does not require Python.

### Arch Linux

Arch Linux users can install the [sacad](https://aur.archlinux.org/packages/sacad/) AUR package.

### From PyPI (with PIP)

1. If you don't already have it, [install pip](https://pip.pypa.io/en/stable/installing/) for Python 3
2. Install SACAD: `pip3 install sacad`

### From source

1. If you don't already have it, [install setuptools](https://pypi.python.org/pypi/setuptools#installation-instructions) for Python 3
2. Clone this repository: `git clone https://github.com/desbma/sacad`
3. Install SACAD: `python3 setup.py install`

#### Optional

Additionally, if you want to benefit from image crunching (lossless recompression to save additional space):

- Install [optipng](http://optipng.sourceforge.net/)
- Install [jpegoptim](http://freecode.com/projects/jpegoptim)

On Ubuntu and other Debian derivatives, you can install both with `sudo apt-get install optipng jpegoptim`.

Note that depending of the speed of your CPU, crunching may significantly slow down processing as it is very CPU intensive (especially for PNG files).

## Command line usage

Two tools are provided: `sacad` to search and download one cover, and `sacad_r` to scan a music library and download all missing covers.

Run `sacad -h` / `sacad_r -h` to get full command line reference.

### Examples

To download the cover of _Master of Puppets_ from _Metallica_, to the file `AlbumArt.jpg`, targetting ~ 600x600 pixel resolution: `sacad "metallica" "master of puppets" 600 AlbumArt.jpg`.

To download covers for your library with the same parameters as previous example: `sacad_r library_directory 600 AlbumArt.jpg`.

## Limitations

- Only supports front covers

## Adding cover sources

Adding a new cover source is very easy if you are a Python developer, you need to inherit the `CoverSource` class and implement the following methods:

- `getSearchUrl(self, album, artist)`
- `parseResults(self, api_data)`
- `updateHttpHeaders(self, headers)` (optional)

See comments in the code for more information.

## License

[Mozilla Public License Version 2.0](https://www.mozilla.org/MPL/2.0/)
