#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from setuptools import find_packages, setup

VERSION = "1.0.0"


with open("requirements.txt", "rt") as f:
  requirements= f.read().splitlines()

setup(name="sacad",
      version=VERSION,
      author="desbma",
      packages=find_packages(),
      entry_points={"console_scripts": ["sacad = sacad:cl_main"]},
      package_data={"": ["LICENSE", "README.md", "requirements.txt"]},
      test_suite="tests",
      install_requires=requirements,
      description="Search and download music album covers",
      url="https://github.com/desbma/sacad",
      download_url="https://github.com/desbma/sacad/archive/%s.tar.gz" % (VERSION),
      keywords=["dowload", "album", "cover", "art", "albumart", "music"],
      classifiers=["Development Status :: 4 - Beta",
                   "Environment :: Console",
                   "Intended Audience :: End Users/Desktop",
                   "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)",
                   "Natural Language :: English",
                   "Operating System :: OS Independent",
                   "Programming Language :: Python",
                   "Programming Language :: Python :: 3",
                   "Programming Language :: Python :: 3 :: Only",
                   "Programming Language :: Python :: 3.3",
                   "Programming Language :: Python :: 3.4",
                   "Topic :: Internet :: WWW/HTTP",
                   "Topic :: Multimedia :: Graphics",
                   "Topic :: Utilities"])
