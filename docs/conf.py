from __future__ import annotations

import importlib.metadata

import sphinx

sphinx.SPHINX_RUNNING = True

# -- Project information -----------------------------------------------------

metadata = importlib.metadata.metadata("whenever")

project = metadata["Name"]
version = metadata["Version"]
release = metadata["Version"]


# -- General configuration ------------------------------------------------

nitpicky = True
nitpick_ignore = [
    ("py:class", "whenever._pywhenever._T"),
    (
        "py:class",
        "TypeAliasForwardRef",
    ),  # https://github.com/sphinx-doc/sphinx/issues/11327
]
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx_reredirects",
    "sphinx_llm.txt",
    "sphinx_copybutton",
    "sphinx_design",
    "myst_parser",
]
templates_path = ["_templates"]
source_suffix = {
    ".md": "markdown",
    ".rst": "restructuredtext",
}
redirects = {
    "api": "reference/datetime.html",
    "benchmarks": "performance.html",
    "deltas": "reference/deltas.html",
    "overview": "guide/index.html",
    "reference/deprecated": "changelog.html",
}
html_static_path = ["_static"]
html_title = "Whenever"

master_doc = "index"
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
myst_heading_anchors = 2
myst_enable_extensions = [
    "colon_fence",
    "smartquotes",
    "deflist",
]

# -- Options for HTML output ----------------------------------------------

autodoc_default_options = {
    "exclude-members": "__weakref__, __init__, __init_subclass__, __reduce__, __hash__, __repr__, __subclasshook__, __class_getitem__",
}
autodoc_member_order = "groupwise"
html_theme = "furo"
llms_txt_description = (
    "A type-safe Python datetime library with DST-correct arithmetic and "
    "distinct instant, zoned, offset, and plain datetime types."
)
llms_txt_suffix_mode = "replace"
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
    "OffsetMismatchStr": "OffsetMismatchStr",
}
