SACAD
=====
Smart Automatic Cover Art Downloader
------------------------------------

SACAD is a multi platform command line tool to download album covers without manual intervention, ideal for integration in scripts, audio players, etc.


## Features

* Can target specific image size
* Support JPEG and PNG formats
* Currently support 4 cover sources:
    * Last.fm
    * Google Images
    * ecover.to
    * Amazon.com
* Smart sorting algorithm to select THE best cover for a given query, using several factors: source reliability, image format, image size, image similarity with reference cover, etc.
* Automatically crunch images with optipng or jpegoptim (can save 30% of filesize without any loss of quality, great for portable players)
* Cache search results locally for faster future search
* Do everything to avoid getting blocked by the sources: hide user-agent and automatically take care of rate limiting
* Automatically convert/resize image if needed
* Multiplatform (Windows/Max/ Linux)

SACAD is designed to be robust and be executed in batch of thousands of queries:

* HTML parsing is done without regex but with the LXML library, which is faster, and more robust to page changes
* When the size of an image reported by a source is not reliable (ie. Google Images), automatically download the first KB of the file to get its real size from the file header
* Use multithreading when relevant, to speed up processing


## Command line reference

    usage: sacad.py [-h] [-t SIZE_TOLERANCE_PRCT] [-d] [-e]
                    [-v {quiet,warning,normal,debug}]
                    artist album size out_filepath

    Download an album cover

    positional arguments:
      artist                Artist to search for
      album                 Album to search for
      size                  Target image size
      out_filepath          Output image file

    optional arguments:
      -h, --help            show this help message and exit
      -t SIZE_TOLERANCE_PRCT, --size-tolerance SIZE_TOLERANCE_PRCT
                            Tolerate this percentage of size difference with the
                            target size. Note that covers with size above or close
                            to the target size will still be preferred if
                            available
      -d, --disable-low-quality-sources
                            Disable cover sources that may return unreliable
                            results (ie. Google Images). It will speed up
                            processing and improve reliability, but may fail to
                            find results for some difficult searches.
      -e, --https           Use SSL encryption (HTTPS) when available
      -v {quiet,warning,normal,debug}, --verbosity {quiet,warning,normal,debug}
                            Level of output to display


## Installation

**SACAD needs Python >= 3.3**.

1. Clone this repository
2. If you don't have it, [install pip](http://www.pip-installer.org/en/latest/installing.html) for Python3 (not needed if you are using Python >= 3.4)
3. Install Python dependencies: `pip3 install -r requirements.txt`

You are ready to download a cover, ie: `./sacad.py 'metallica' 'master of puppets' 600 cover.jpg`

Windows users can also [download a standalone binary](https://dl.dropboxusercontent.com/u/70127955/sacad_20140628_win.7z) which does not require Python.

#### Optional

Additionnaly, if you want to benefit from image crunching (lossless recompression):

* Install [optipng](http://optipng.sourceforge.net/)
* Install [jpegoptim](http://freecode.com/projects/jpegoptim)

On Ubuntu and other Debian derivatives, you can install both with `sudo apt-get install optipng jpegoptim`.

Note that depending of the speed of your CPU, crunching may significantly slow down processing as it is very CPU intensive (especially for PNG files).


## Adding cover sources

Adding a new cover source is very easy if you speak Python, you need to inherit the `CoverSource` class and implement the following methods:

* `getSearchUrl(self, album, artist)`
* `updateHttpHeaders(self, headers)`
* `parseResults(self, api_data)`

See comments in the code for more information.


## Limitations

* Only supports front covers

## License

[Mozilla Public License Version 2.0](https://www.mozilla.org/MPL/2.0/)
