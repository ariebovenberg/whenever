# See pyproject.toml for why this file exists.
import os
import platform

from setuptools import build_meta as _setuptools
from setuptools.build_meta import *

_ENV_VAR = "WHENEVER_NO_BUILD_RUST_EXT"
_SETTING = "rust-extension"


def _apply(config_settings):
    """Read our config setting, e.g. ``-C rust-extension=skip``.

    setup.py only sees setuptools' own settings, so a skip reaches it
    through the environment variable. Returns the settings without ours.
    """
    settings = dict(config_settings or {})
    value = settings.pop(_SETTING, "build")
    if value == "skip":
        os.environ[_ENV_VAR] = "1"
    elif value != "build":
        raise ValueError(
            f"config setting {_SETTING} must be 'build' or 'skip', got {value!r}"
        )
    return settings or None


def _build_deps():
    if os.getenv(_ENV_VAR) or platform.python_implementation() in (
        "PyPy",
        "GraalVM",
    ):
        return []
    return ["setuptools-rust"]


def get_requires_for_build_wheel(config_settings=None):
    _apply(config_settings)
    return _build_deps()


def get_requires_for_build_sdist(config_settings=None):
    _apply(config_settings)
    return _build_deps()


def get_requires_for_build_editable(config_settings=None):
    _apply(config_settings)
    return _build_deps()


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    return _setuptools.prepare_metadata_for_build_wheel(
        metadata_directory, _apply(config_settings)
    )


def prepare_metadata_for_build_editable(
    metadata_directory, config_settings=None
):
    return _setuptools.prepare_metadata_for_build_editable(
        metadata_directory, _apply(config_settings)
    )


def build_wheel(
    wheel_directory, config_settings=None, metadata_directory=None
):
    return _setuptools.build_wheel(
        wheel_directory, _apply(config_settings), metadata_directory
    )


def build_sdist(sdist_directory, config_settings=None):
    return _setuptools.build_sdist(sdist_directory, _apply(config_settings))


def build_editable(
    wheel_directory, config_settings=None, metadata_directory=None
):
    return _setuptools.build_editable(
        wheel_directory, _apply(config_settings), metadata_directory
    )
