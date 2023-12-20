from __future__ import annotations

# -- Project information -----------------------------------------------------
import importlib.metadata
import typing
typing.SPHINX_BUILD = True

metadata = importlib.metadata.metadata("whenever")

project = metadata["Name"]
version = metadata["Version"]
release = metadata["Version"]


# -- General configuration ------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx_copybutton",
]
templates_path = ["_templates"]
source_suffix = ".rst"

master_doc = "index"
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Options for HTML output ----------------------------------------------

autodoc_member_order = "bysource"
html_theme = "furo"
highlight_language = "python3"
pygments_style = "default"
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}
