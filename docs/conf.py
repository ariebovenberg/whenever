from __future__ import annotations

import importlib.metadata
import re

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
    ("py:class", "_SystemTZ"),
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
    "sphinxext.opengraph",
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
    "guide/ambiguity": "resolving-local-times.html",
    "overview": "guide/index.html",
    "reference/deprecated": "../changelog.html",
}
html_static_path = ["_static"]
html_title = "Whenever"
# Used by _templates/base.html for the homepage <title> only.
html_context = {"homepage_title": "Whenever — type-safe datetimes for Python"}
# Point every version's canonical URL at latest, so that search engines don't
# have to choose between the identical copies under /en/<version>/.
html_baseurl = "https://whenever.readthedocs.io/en/latest/"

master_doc = "index"
exclude_patterns = ["_build", "adr", "internal", "Thumbs.db", ".DS_Store"]
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
# Open Graph tags, so links to the docs get a title and a summary when shared.
ogp_site_url = html_baseurl
ogp_site_name = "Whenever"
ogp_social_cards = {"enable": False}  # would pull in matplotlib
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
    "DeltaTotalUnitStr": "DeltaTotalUnitStr",
    "DateDeltaUnitStr": "DateDeltaUnitStr",
    "ExactDeltaUnitStr": "ExactDeltaUnitStr",
    "DisambiguationStr": "DisambiguationStr",
    "DisambiguateStr": "DisambiguateStr",
    "OffsetMismatchStr": "OffsetMismatchStr",
    "TimestampUnitStr": "TimestampUnitStr",
    "_SystemTZ": "SYSTEM_TZ",
}


# The 0.11 compatibility shims absorb their old keyword through a `**kwargs`
# catch-all. That's an implementation detail, so hide it from the rendered
# signature. Remove along with the shims in 1.0.
_SHIM_KWARGS_MEMBERS = frozenset(
    {
        "whenever.Date.parse",
        "whenever.Instant.parse",
        "whenever.OffsetDateTime.parse",
        "whenever.PlainDateTime.parse",
        "whenever.PlainDateTime.assume_tz",
        "whenever.PlainDateTime.assume_system_tz",
        "whenever.Time.parse",
        "whenever.ZonedDateTime.parse",
        "whenever.ZonedDateTime.parse_iso",
        "whenever.ZonedDateTime.from_system_tz",
        "whenever.ZonedDateTime.format_iso",
        "whenever.ZonedDateTime.replace_date",
        "whenever.ZonedDateTime.replace_time",
    }
)
_SHIM_KWARGS_PARAM = re.compile(r",\s*\*\*kwargs(?::[^,)]*)?")


def _hide_shim_kwargs(
    app, what, name, obj, options, signature, return_annotation
):
    if name in _SHIM_KWARGS_MEMBERS and signature:
        stripped = _SHIM_KWARGS_PARAM.sub("", signature)
        assert stripped != signature, f"no catch-all to hide in {name}"
        return stripped, return_annotation
    return None


def setup(app):
    app.connect("autodoc-process-signature", _hide_shim_kwargs)
