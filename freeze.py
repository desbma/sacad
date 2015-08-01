#!/usr/bin/env python3

import os
import re

from cx_Freeze import setup, Executable
import requests


with open(os.path.join("sacad", "__init__.py"), "rt") as f:
  version = re.search("__version__ = \"([^\"]+)\"", f.read()).group(1)

build_exe_options = {"includes": ["lxml._elementpath", "cssselect"],
                     "include_files": [(requests.certs.where(), "cacert.pem")],
                     "optimize": 0}

setup(name="sacad",
      version=version,
      author="desbma",
      packages=["sacad"],
      options={"build_exe": build_exe_options},
      executables=[Executable(os.path.join("sacad", "__main__.py"),
                              targetName="sacad.exe")])
