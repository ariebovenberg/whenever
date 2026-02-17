from __future__ import annotations
import sphinx

sphinx.SPHINXBUILD = True

# -- Project information -----------------------------------------------------
import importlib.metadata

metadata = importlib.metadata.metadata("whenever")

project = metadata["Name"]
version = metadata["Version"]
release = metadata["Version"]


# -- General configuration ------------------------------------------------

nitpicky = True
nitpick_ignore = [
    ("py:class", "whenever._pywhenever._T"),
]
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx_copybutton",
    "myst_parser",
]
templates_path = ["_templates"]
source_suffix = {
    ".md": "markdown",
    ".rst": "restructuredtext",
}
html_static_path = ["_static"]
html_title = "Whenever"

master_doc = "index"
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
myst_heading_anchors = 2
myst_enable_extensions = [
    "colon_fence",
    "smartquotes",
]

# -- Options for HTML output ----------------------------------------------

autodoc_default_options = {
    "exclude-members": "__weakref__, __init__, __init_subclass__, __reduce__, __hash__, __repr__, __subclasshook__, __class_getitem__",
}
autodoc_member_order = "groupwise"
html_theme = "furo"
highlight_language = "python3"
pygments_style = "default"
pygments_dark_style = "lightbulb"
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}
toc_object_entries_show_parents = "hide"
maximum_signature_line_length = 150
# Awaiting https://github.com/sphinx-doc/sphinx/issues/14003
autodoc_type_aliases = {
    "RoundModeStr": "RoundModeStr",
    "DeltaUnitStr": "DeltaUnitStr",
    "DateDeltaUnitStr": "DateDeltaUnitStr",
    "ExactDeltaUnitStr": "ExactDeltaUnitStr",
    "DisambiguateStr": "DisambiguateStr",
    "AnyDelta": "AnyDelta",
}
