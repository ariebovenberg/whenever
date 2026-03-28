"""
Generate comparison bar charts from benchmark results.

Produces two SVG files (one per theme):

  timing-light.svg, timing-dark.svg   — grid, one subplot per benchmark
  readme-draft-light.svg, readme-draft-dark.svg   — compact single-benchmark chart

Run:

    uv run python charts.py
    uv run python charts.py --output ../../docs/_static/benchmarks/

To change the chart colour scheme, adjust BRAND_HUE_DEG below.
"""

from __future__ import annotations

import argparse
import colorsys
import json
import math
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pyperf

# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------

# Standard "GitHub / browser" system font stack — used in the generated SVGs so
# they render in the OS UI font (San Francisco, Segoe UI, etc.) rather than the
# font matplotlib happened to have installed.
_SYSTEM_FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

# rcParams applied to every plot function via rc_context so text is emitted as
# real <text> elements (not glyph paths), enabling the system font stack above
# and shrinking the SVG ~20×.
_SVG_RC = {
    "svg.fonttype": "none",
    "font.family": "sans-serif",
    "font.sans-serif": [
        "Helvetica Neue",
        "Helvetica",
        "Arial",
        "Liberation Sans",
        "DejaVu Sans",
    ],
}


def _save_svg(fig: plt.Figure, output: Path, tight_text: bool = False) -> None:
    """Save figure as SVG and inject a system UI font stack into text elements.

    With svg.fonttype=none matplotlib writes the locally-resolved font name
    (e.g. "Helvetica Neue" or "DejaVu Sans") into style attributes.  Replacing
    it with the full system stack means any browser renders in its native UI
    font, matching the surrounding page typography.

    If tight_text is True, also inject a small negative letter-spacing to match
    the tighter tracking of system UI fonts (SF Pro, Segoe UI) vs the wider
    spacing of typical matplotlib fallback fonts.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, format="svg", transparent=True)
    svg = output.read_text()
    svg = re.sub(
        r'font-family:[^;"]+',
        f"font-family: {_SYSTEM_FONT}",
        svg,
    )
    if tight_text:
        # Inject after font-family so the browser applies tighter tracking.
        svg = re.sub(
            r"(font-family:[^;\"]+)",
            r"\1; letter-spacing: -0.3px",
            svg,
        )
    output.write_text(svg)
    print(f"  Saved {output}")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# ── Brand colour ─────────────────────────────────────────────────────────────
# Change BRAND_HUE_DEG (0–360) to re-colour all charts at once.
BRAND_HUE_DEG: float = 0.0

# Top-to-bottom in each subplot (first = top = fastest).
# whenever_pure is intentionally excluded from charts; see docs for details.
LIBRARY_ORDER = ["whenever", "stdlib", "arrow", "pendulum"]

# (NOTE: for now, the same saturation for all libraries)
# (saturation, lightness) stops for each library slot, darkest → lightest.
# Ordered to match LIBRARY_ORDER.
_LIGHT_STOPS: tuple[tuple[float, float], ...] = (
    # (0.64, 0.28),  # whenever  — darkest
    (0.55, 0.59),   # datetime
    # (0.56, 0.70),   # arrow
    # (0.59, 0.85),   # pendulum  — lightest
) * 4
_DARK_STOPS: tuple[tuple[float, float], ...] = (
    (0.55, 0.59),  # whenever
    # (0.54, 0.69),   # datetime
    # (0.63, 0.83),   # arrow
    # (0.52, 0.92),   # pendulum
) * 4


def _hsl_hex(h_deg: float, s: float, l: float) -> str:
    """HSL → #rrggbb.  h in degrees [0–360], s and l in [0, 1]."""
    # colorsys uses HLS order (not HSL)
    r, g, b = colorsys.hls_to_rgb(h_deg / 360.0, l, s)
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def _make_palette(
    hue: float, stops: tuple[tuple[float, float], ...]
) -> dict[str, str]:
    return {
        lib: _hsl_hex(hue, s, l) for lib, (s, l) in zip(LIBRARY_ORDER, stops)
    }


COLORS_LIGHT = _make_palette(BRAND_HUE_DEG, _LIGHT_STOPS)
COLORS_DARK = _make_palette(BRAND_HUE_DEG, _DARK_STOPS)

LIBRARY_LABELS: dict[str, str] = {
    "whenever": "Whenever",
    "stdlib": "datetime",
    "whenever_pure": "Whenever (py)",
    "arrow": "Arrow",
    "pendulum": "Pendulum",
}

BENCHMARK_ORDER = [
    "now",
    "shift",
    "format_iso",
    "parse_iso",
    "instantiate_zdt",
    "to_tz",
    "normalize_utc",
    "difference",
    # "calendar_shift",
]

BENCHMARK_LABELS: dict[str, str] = {
    "now": "now()",
    "parse_iso": "parse ISO string",
    "instantiate_zdt": "instantiate ZDT",
    "shift": "shift",
    "to_tz": "change timezone",
    "normalize_utc": "normalize to UTC",
    "format_iso": "format ISO string",
    "difference": "time difference",
    # "calendar_shift": "calendar shift",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_ns(ns: float) -> str:
    """Format a nanosecond value as a compact human-readable label."""
    if ns < 1_000:
        return f"{ns:.0f} ns"
    if ns < 1_000_000:
        val = ns / 1_000
        return f"{val:.1f} µs" if val < 10 else f"{val:.0f} µs"
    return f"{ns/1_000_000:.1f} ms"


def _compute_cutoff(values: list[float]) -> float:
    """Linear-scale cutoff = (3rd smallest value) × 6.

    This keeps the three fastest libraries fully visible while clipping
    extreme outliers, preventing the scale from being dominated by a single
    very slow data point.
    """
    valid = sorted(v for v in values if math.isfinite(v) and v > 0)
    if not valid:
        return 1.0
    # Use the 3rd smallest as the anchor; fall back if fewer values.
    anchor_idx = min(2, len(valid) - 1)
    return valid[anchor_idx] * 6


def _axis_unit(cutoff_ns: float) -> tuple[str, float]:
    """Return (unit_label, divisor) for the x-axis of a timing subplot."""
    if cutoff_ns >= 2_000:
        return "µs", 1_000
    return "ns", 1


# ---------------------------------------------------------------------------
# Timing chart
# ---------------------------------------------------------------------------


def _plot_timing_subplot(
    ax: plt.Axes,
    benchmark: str,
    timing: dict[str, dict[str, float]],
    colors: dict[str, str],
    text_color: str,
    grid_color: str,
) -> None:
    libs = LIBRARY_ORDER
    n_libs = len(libs)

    values = [timing.get(lib, {}).get(benchmark, float("nan")) for lib in libs]
    valid_vals = [v for v in values if math.isfinite(v)]
    cutoff = _compute_cutoff(valid_vals) if valid_vals else 1.0

    unit, divisor = _axis_unit(cutoff)

    # y-positions: lib[0] (whenever) at the top (highest y), lib[-1] at bottom.
    y_pos = np.arange(n_libs - 1, -1, -1, dtype=float)  # [4, 3, 2, 1, 0]

    for i, (lib, y) in enumerate(zip(libs, y_pos)):
        val = values[i]
        if not math.isfinite(val):
            continue

        color = colors[lib]
        clipped = val > cutoff
        bar_val = cutoff if clipped else val

        # Ensure even very small bars are visually present (min 1% of axis width)
        display_val = max(bar_val, cutoff * 0.008)

        ax.barh(
            y,
            display_val,
            height=0.65,
            color=color,
            edgecolor="none",
            zorder=3,
        )

        # Value label
        label_str = f"> {_fmt_ns(val)}" if clipped else _fmt_ns(val)
        label_x = bar_val + cutoff * 0.03
        ax.text(
            label_x,
            y,
            label_str,
            va="center",
            ha="left",
            fontsize=12,
            color=text_color,
            zorder=4,
            clip_on=False,
        )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(
        [LIBRARY_LABELS[lib] for lib in libs],
        fontsize=12,
        color=text_color,
    )
    ax.tick_params(axis="y", length=0, pad=4)

    ax.set_xlim(0, cutoff * 1.45)  # extra room for clipped-bar labels
    ax.xaxis.set_major_formatter(
        mticker.FuncFormatter(
            lambda x, _: (
                f"{x/divisor:.1f}" if x / divisor < 10 else f"{x/divisor:.0f}"
            )
        )
    )
    # ax.set_xlabel(unit, fontsize=8, color=text_color, labelpad=2)
    ax.tick_params(axis="x", labelsize=10, colors=text_color, length=0)

    ax.set_title(
        BENCHMARK_LABELS.get(benchmark, benchmark),
        fontsize=14,
        color=text_color,
        pad=5,
        fontweight="semibold",
    )

    ax.set_facecolor("none")
    ax.grid(True, axis="x", color=grid_color, linewidth=0.6, zorder=0)
    ax.grid(False, axis="y")

    for spine in ax.spines.values():
        spine.set_visible(False)


def plot_timing(
    timing: dict[str, dict[str, float]],
    output: Path,
    theme: str,
) -> None:
    """Generate a grid of timing subplots and save as SVG."""
    colors = COLORS_DARK if theme == "dark" else COLORS_LIGHT
    text_color = "#dde8f0" if theme == "dark" else "#333333"
    grid_color = "#3a4a5a" if theme == "dark" else "#e0e0e0"

    benchmarks = [
        b
        for b in BENCHMARK_ORDER
        if any(b in timing.get(lib, {}) for lib in LIBRARY_ORDER)
    ]

    ncols, nrows = 2, math.ceil(len(benchmarks) / 2)
    with plt.rc_context(_SVG_RC):
        fig, axes = plt.subplots(nrows, ncols, figsize=(11, 2 * nrows))
        fig.patch.set_alpha(0)

        for idx, bm in enumerate(benchmarks):
            row, col = divmod(idx, ncols)
            ax = axes[row][col] if nrows > 1 else axes[col]
            _plot_timing_subplot(
                ax, bm, timing, colors, text_color, grid_color
            )

        # Hide unused subplots
        for idx in range(len(benchmarks), nrows * ncols):
            row, col = divmod(idx, ncols)
            ax = axes[row][col] if nrows > 1 else axes[col]
            ax.set_visible(False)

        fig.text(
            0.5,
            0.005,
            "Lower is better  ·  '> X' indicates bar exceeds the axis cutoff",
            ha="center",
            fontsize=14,
            color=text_color,
            style="italic",
        )
        plt.tight_layout(rect=[0, 0.03, 1, 1], h_pad=1.5, w_pad=2.0)
        _save_svg(fig, output)
        plt.close(fig)


# ---------------------------------------------------------------------------
# README-style draft chart
# ---------------------------------------------------------------------------

# Data for the compact README chart — comes from the compound benchmark.
# Values are in seconds (total time for a large batch of ops).
_README_DATA: list[tuple[str, float, str]] = [
    # (label,          seconds, formatted)
    ("Whenever", 0.37, "0.4s"),
    ("datetime", 1.88, "1.9s"),
    ("Whenever (pure python)", 9.1, "9.1s"),
    ("Arrow", 34, "34s"),
    ("Pendulum", 89, "91s"),
]


def plot_readme_style(
    output: Path,
    theme: str,
) -> None:
    """Compact single-column chart for the README.

    Mirrors the style of the Vega-Lite graph that it is intended to replace.
    """
    libs = [d[0] for d in _README_DATA]
    values = [d[1] for d in _README_DATA]
    fmt = [d[2] for d in _README_DATA]

    highlight = libs[0]

    text_color = "#dde8f0" if theme == "dark" else "#333333"
    grid_color = (
        (0.3, 0.3, 0.3, 0.15) if theme == "dark" else (0.8, 0.8, 0.8, 0.15)
    )
    bar_color = "#E15759"

    n = len(libs)
    # Half-unit spacing: slots at 0.0, 0.5, 1.0, ... top-to-bottom
    y_pos = np.arange(0, n * 0.5, 0.5)[::-1].copy()

    with plt.rc_context(_SVG_RC):
        fig, ax = plt.subplots(figsize=(6.25, 0.18 * n + 0.38))
        fig.patch.set_alpha(0)
        ax.set_facecolor("none")

        max_val = max(values)
        for lib, val, lbl, y in zip(libs, values, fmt, y_pos):
            ax.barh(
                y,
                val,
                height=0.30,
                color=bar_color,
                edgecolor="none",
                zorder=3,
            )
            if lbl:
                ax.text(
                    val + max_val * 0.02,
                    y,
                    lbl,
                    va="center",
                    ha="left",
                    fontsize=9,
                    color=text_color,
                    fontweight="bold" if lib == highlight else "normal",
                    zorder=4,
                    clip_on=False,
                )

        ax.set_yticks(y_pos)
        ax.set_yticklabels(
            libs, fontsize=9, color=text_color, verticalalignment="center"
        )
        # Bold the highlighted library's y-axis label after draw
        fig.canvas.draw()
        for tick_lbl in ax.get_yticklabels():
            if tick_lbl.get_text() == highlight:
                tick_lbl.set_fontweight("bold")

        ax.tick_params(axis="y", length=0, pad=6)
        ax.set_ylim(y_pos[-1] - 0.25, y_pos[0] + 0.25)
        ax.set_xlim(0, max_val * 1.05)
        ax.xaxis.set_major_formatter(
            mticker.FuncFormatter(lambda x, _: f"{x:.0f}s")
        )
        ax.tick_params(
            axis="x", labelsize=9, colors=text_color, length=0, pad=4
        )

        ax.grid(True, axis="x", color=grid_color, linewidth=0.5, zorder=0)
        ax.grid(False, axis="y")
        for spine in ax.spines.values():
            spine.set_visible(False)

        # Explicit left margin so the longest y-label ("Whenever (pure python)")
        # is never clipped, regardless of local font metrics vs browser rendering.
        fig.subplots_adjust(left=0.30, right=0.80, top=0.95, bottom=0.18)
        _save_svg(fig, output, tight_text=True)
        plt.close(fig)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_timing(results_dir: Path) -> dict[str, dict[str, float]]:
    """Return {library: {benchmark: mean_ns}}."""
    data: dict[str, dict[str, float]] = {}
    for lib in LIBRARY_ORDER:
        path = results_dir / f"result_{lib}.json"
        if not path.exists():
            print(
                f"  Warning: {path} not found — skipping {lib}",
                file=sys.stderr,
            )
            continue
        suite = pyperf.BenchmarkSuite.load(str(path))
        data[lib] = {b.get_name(): b.mean() * 1e9 for b in suite}
    return data


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    here = Path(__file__).parent
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--results-dir",
        default=str(here / "results"),
        metavar="DIR",
        help="directory containing result_*.json files (default: results/)",
    )
    parser.add_argument(
        "--output",
        default=str(here / "charts"),
        metavar="DIR",
        help="output directory for SVG files (default: charts/)",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    out_dir = Path(args.output)

    print("Loading timing results…")
    timing = load_timing(results_dir)
    if not timing:
        sys.exit("No result files found. Run ./run.sh first.")

    print("Generating charts…")
    for theme in ("light", "dark"):
        plot_timing(timing, out_dir / f"timing-{theme}.svg", theme)

    print("Generating README-style chart…")
    for theme in ("light", "dark"):
        plot_readme_style(out_dir / f"readme-draft-{theme}.svg", theme)

    print("Done.")


if __name__ == "__main__":
    main()
