#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re

from cx_Freeze import setup, Executable


with open(os.path.join("sacad", "__init__.py"), "rt") as f:
  version = re.search("__version__ = \"([^\"]+)\"", f.read()).group(1)

build_exe_options = {"includes": ["lxml._elementpath", "cssselect"],
                     "optimize": 0}

setup(name="sacad",
      version=version,
      author="desbma",
      packages=["sacad"],
      options={"build_exe": build_exe_options},
      executables=[Executable("freeze_wrapper.py",
                              targetName="sacad.exe")])
