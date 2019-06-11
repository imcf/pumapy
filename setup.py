#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Setup for the pumapy package, details are in `setup.cfg`."""

from __future__ import print_function

import sys

from pkg_resources import require, VersionConflict
from setuptools import setup

try:
    require('setuptools>=38.3')
except VersionConflict:
    print("Error: version of setuptools is too old (<38.3)!")
    sys.exit(1)


if __name__ == "__main__":
    setup(install_requires=['requests'])
