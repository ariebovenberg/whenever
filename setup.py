import os

from setuptools import setup
from setuptools_rust import Binding, RustExtension, build_rust

_SKIP_BUILD_SUGGESTION = f"""
*******************************************************************************

Building the Rust extension of the library `whenever` failed. See errors above.
Set the `WHENEVER_NO_BUILD_RUST_EXT` environment variable to any value to skip
building the Rust extension and use the (slower) Python version instead.

*******************************************************************************
"""


class CustomBuildExtCommand(build_rust):
    def run(self):
        try:
            build_rust.run(self)
        except Exception as e:
            print(_SKIP_BUILD_SUGGESTION)
            raise e


setup(
    rust_extensions=[RustExtension("whenever._whenever", binding=Binding.PyO3)]
    * (not os.getenv("WHENEVER_NO_BUILD_RUST_EXT")),
    cmdclass={"build_rust": CustomBuildExtCommand},
)
