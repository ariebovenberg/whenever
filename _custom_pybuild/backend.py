# See pyproject.toml for why this file exists.
from setuptools import build_meta as _orig
from setuptools.build_meta import *
import platform
import os


if os.getenv("WHENEVER_NO_BUILD_RUST_EXT") or (
    platform.python_implementation() in ("PyPy", "GraalVM")
):
    build_deps = []
else:
    build_deps = ["setuptools-rust"]


def get_requires_for_build_wheel(config_settings=None):
    return build_deps


def get_requires_for_build_sdist(config_settings=None):
    return build_deps


def get_requires_for_build_editable(config_settings=None):
    return build_deps
