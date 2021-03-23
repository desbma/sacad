#!/usr/bin/env python3

""" Package freezing for Windows. """

import os
import re
import sys

from cx_Freeze import Executable, setup

os.environ["TCL_LIBRARY"] = os.path.join(os.path.dirname(sys.executable), "tcl", "tcl8.6")
os.environ["TK_LIBRARY"] = os.path.join(os.path.dirname(sys.executable), "tcl", "tk8.6")


with open(os.path.join("sacad", "__init__.py"), "rt") as f:
    version_match = re.search('__version__ = "([^"]+)"', f.read())
assert version_match is not None
version = version_match.group(1)

build_exe_options = {"includes": ["lxml._elementpath"], "packages": ["asyncio", "idna"], "optimize": 0}

setup(
    name="sacad",
    version=version,
    author="desbma",
    packages=["sacad"],
    options={"build_exe": build_exe_options},
    executables=[
        Executable(os.path.join("sacad", "__main__.py"), targetName="sacad.exe"),
        Executable(os.path.join("sacad", "recurse.py"), targetName="sacad_r.exe"),
    ],
)
