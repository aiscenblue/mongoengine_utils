#!/usr/bin/env python
# coding=utf-8
"""Setup script."""

import sys
from setuptools import setup, find_packages

dependencies = ["mongoengine", "dateutils"]
desc = "More human readable JSON serializer/de-serializer, pagination for MongoEngine"
version = "1.0.0"
if sys.version_info < (2, 7):
    raise RuntimeError("Not supported on earlier then python 2.7.")

try:
    from functools import singledispatch
except ImportError:
    dependencies.append("singledispatch")

try:
    with open('README.rst') as readme:
        long_desc = readme.read()
except Exception:
    long_desc = None

setup(
    name="mongoengine_utils",
    version=version,
    description=desc,
    long_description=long_desc,
    packages=["mongoengine_utils"],
    install_requires=dependencies,
    zip_safe=False,
    author="Jeffrey Marvin Forones",
    author_email="aiscenblue@gmail.com",
    license="MIT",
    keywords="json mongoengine mongodb",
    url="https://github.com/aiscenblue/mongoengine_utils",
    classifiers=[
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3.5"
    ]
)
