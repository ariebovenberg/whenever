from __future__ import annotations

import importlib.metadata
import os
import re
import sys
import warnings

import whenever._common
from docutils import nodes
from sphinx_design.shared import PassthroughTextElement

# Document the pure-Python backend: autodoc and viewcode need its source.
sys.modules["whenever._whenever"] = None
# Keeps the internal modules from reporting their members as `whenever`'s,
# which would hide their source from viewcode and their attribute docstrings
# from autodoc (https://github.com/sphinx-doc/sphinx/issues/3673). It must be
# set before the lazily imported modules read it.
whenever._common.SPHINX_RUNNING = True

# viewcode and autodoc resolve the deprecated ``TZPATH`` and
# ``DisambiguateStr`` reference entries by attribute access, which is exactly
# what the deprecation warns about. Remove together with the entries in 1.0.
warnings.filterwarnings("ignore", message="TZPATH is deprecated")
warnings.filterwarnings("ignore", message="DisambiguateStr is deprecated")

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
redirects = {
    "api": "reference/datetime.html",
    "benchmarks": "performance.html",
    "deltas": "reference/deltas.html",
    "guide/ambiguity": "resolving-local-times.html",
    "overview": "guide/index.html",
    "reference/deprecated": "../changelog.html",
}
# The llms.txt markdown build has no handler for the <meta> nodes that
# pages emit through myst's html_meta; dropping them loses nothing.
llms_txt_suppress_unknown_node_warnings = ["meta"]
html_static_path = ["_static"]
html_title = "Whenever"
# Used by _templates/base.html for the homepage <title> only.
html_context = {"homepage_title": "Whenever — type-safe datetimes for Python"}
# Point every version's canonical URL at latest, so that search engines don't
# have to choose between the identical copies under /en/<version>/.
html_baseurl = "https://whenever.readthedocs.io/en/latest/"

exclude_patterns = ["_build", "adr", "internal"]
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
# The llms.txt output is a second full Sphinx build in a subprocess, so it's
# built only on Read the Docs. Pass `-D llms_txt_enabled=1` to build it locally.
llms_txt_enabled = os.environ.get("READTHEDOCS") == "True"
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


# Two renderings Sphinx 9.1 gets wrong inside signatures, fixed on the doctree
# because `@overload` variants never pass through `autodoc-process-signature`:
#
# - an alias from `autodoc_type_aliases` nested in a generic or union prints
#   as `TypeAliasForwardRef('DeltaUnitStr')` instead of `DeltaUnitStr`;
# - the system time zone sentinel is annotated with its private class
#   `_SystemTZ`, which should read (and link) as `SYSTEM_TZ`.
_SYSTEM_TZ_CLASS = re.compile(r"(?:whenever\.(?:_common\.)?)?_SystemTZ")


def _fix_signature_nodes(app, doctree):
    from sphinx import addnodes

    for sig in doctree.findall(addnodes.desc_signature):
        for xref in list(sig.findall(addnodes.pending_xref)):
            if _SYSTEM_TZ_CLASS.fullmatch(xref.get("reftarget", "")):
                xref["reftarget"] = "whenever.SYSTEM_TZ"
                xref["reftype"] = "data"
        for text in list(sig.findall(nodes.Text)):
            if _SYSTEM_TZ_CLASS.fullmatch(text.astext()):
                text.parent.replace(text, nodes.Text("SYSTEM_TZ"))
        # The forward reference is tokenized into four siblings:
        # `TypeAliasForwardRef`, `(`, `'Name'`, and `)`.
        for text in list(sig.findall(nodes.Text)):
            if text.astext() != "TypeAliasForwardRef":
                continue
            node, parent = text, text.parent
            if len(parent) == 1:
                node, parent = parent, parent.parent
            i = parent.index(node)
            tokens = [n.astext() for n in parent[i : i + 4]]
            if len(tokens) < 4 or tokens[1] != "(" or tokens[3] != ")":
                continue  # pragma: no cover
            name = tokens[2].strip("'\"")
            for _ in range(4):
                parent.remove(parent[i])
            parent.insert(i, addnodes.desc_sig_name(name, name))


# sphinx-markdown-builder drops these nodes from the llms.txt output.
# The admonition handler reuses its private box helpers, as its named
# admonitions (note, hint, ...) do.
def _visit_admonition_md(self, node):
    title, *body = node.children
    self._push_box(title.astext())
    for c in body:
        c.walkabout(self)
    self._pop_context()
    raise nodes.SkipNode


def _visit_attribution_md(self, node):
    self.add(f"-- {node.astext()}", prefix_eol=2)
    raise nodes.SkipNode


def _pass_md(self, node):
    pass


def _depart_passthrough_md(self, node):
    self.ensure_eol(2)


def setup(app):
    app.connect("autodoc-process-signature", _hide_shim_kwargs)
    app.connect("doctree-read", _fix_signature_nodes)
    for node, handlers in [
        (nodes.admonition, (_visit_admonition_md, None)),
        (nodes.attribution, (_visit_attribution_md, None)),
        (PassthroughTextElement, (_pass_md, _depart_passthrough_md)),
        (nodes.abbreviation, (_pass_md, _pass_md)),
    ]:
        app.add_node(node, override=True, **{"llms-markdown": handlers})
