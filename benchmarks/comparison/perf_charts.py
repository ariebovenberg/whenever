"""
Generate import-time and package-size bar charts.

Produces SVG files matching the visual style of the main timing charts:

  import-time-light.svg, import-time-dark.svg
  package-size-light.svg, package-size-dark.svg

Run (from this directory):

    uv run python perf_charts.py
    uv run python perf_charts.py --output ../../docs/_static/benchmarks/

Import time is measured by spawning fresh Python subprocesses.  Results
are hardware-dependent; the script prints them before generating charts.

Package sizes are based on manylinux_2_17_x86_64 cp313 wheels from PyPI
(updated manually when new versions are released).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from statistics import median

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# ---------------------------------------------------------------------------
# Font/SVG helpers (shared with charts.py)
# ---------------------------------------------------------------------------

_SYSTEM_FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

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


def _save_svg(fig: plt.Figure, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, format="svg", transparent=True)
    svg = output.read_text()
    svg = re.sub(
        r'font-family:[^;"]+',
        f"font-family: {_SYSTEM_FONT}",
        svg,
    )
    output.write_text(svg)
    print(f"  Saved {output}")


# ---------------------------------------------------------------------------
# Import time measurement
# ---------------------------------------------------------------------------

_IMPORT_SNIPPET = """\
import time
t0 = time.perf_counter_ns()
import {module}
print(time.perf_counter_ns() - t0)
"""

_IMPORT_FIRST_USE_SNIPPET = """\
import time
t0 = time.perf_counter_ns()
import whenever
whenever.Instant.now()
print(time.perf_counter_ns() - t0)
"""


def measure_import(module: str, python: str, n: int = 15) -> float:
    """Measure median import time (ns) by spawning fresh processes."""
    if module == "whenever (first use)":
        snippet = _IMPORT_FIRST_USE_SNIPPET
    else:
        snippet = _IMPORT_SNIPPET.format(module=module)
    times = []
    for _ in range(n):
        result = subprocess.run(
            [python, "-c", snippet],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            times.append(int(result.stdout.strip()))
    if not times:
        return float("nan")
    return median(times)


# ---------------------------------------------------------------------------
# Import time chart
# ---------------------------------------------------------------------------

# Modules to measure, in chart order (top to bottom)
IMPORT_MODULES = [
    "whenever",
    "whenever (first use)",
    "datetime",
    "json",
    "arrow",
    "pendulum",
]
IMPORT_LABELS = {
    "whenever": "whenever\n(import only)",
    "whenever (first use)": "whenever\n(first use)",
    "datetime": "datetime",
    "json": "json",
    "arrow": "Arrow",
    "pendulum": "Pendulum",
}


def plot_import_time(
    times_ns: dict[str, float],
    output: Path,
    theme: str,
) -> None:
    text_color = "#dde8f0" if theme == "dark" else "#333333"
    grid_color = "#3a4a5a" if theme == "dark" else "#e0e0e0"
    bar_color = "#E15759"

    modules = [m for m in IMPORT_MODULES if m in times_ns]
    values_ms = [times_ns[m] / 1e6 for m in modules]
    labels = [IMPORT_LABELS.get(m, m) for m in modules]

    n = len(modules)
    y_pos = np.arange(n - 1, -1, -1, dtype=float)

    with plt.rc_context(_SVG_RC):
        fig, ax = plt.subplots(figsize=(5, 0.55 * n + 0.5))
        fig.patch.set_alpha(0)
        ax.set_facecolor("none")

        max_val = max(values_ms) if values_ms else 1.0

        for i, (val, y) in enumerate(zip(values_ms, y_pos)):
            ax.barh(
                y,
                val,
                height=0.55,
                color=bar_color,
                edgecolor="none",
                zorder=3,
            )
            ax.text(
                val + max_val * 0.02,
                y,
                f"{val:.1f} ms",
                va="center",
                ha="left",
                fontsize=9,
                color=text_color,
                zorder=4,
                clip_on=False,
            )

        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=9, color=text_color)
        ax.tick_params(axis="y", length=0, pad=6)

        ax.set_xlim(0, max_val * 1.35)
        ax.xaxis.set_major_formatter(
            mticker.FuncFormatter(lambda x, _: f"{x:.0f} ms")
        )
        ax.tick_params(axis="x", labelsize=8, colors=text_color, length=0)

        ax.grid(True, axis="x", color=grid_color, linewidth=0.6, zorder=0)
        ax.grid(False, axis="y")
        for spine in ax.spines.values():
            spine.set_visible(False)

        plt.tight_layout()
        _save_svg(fig, output)
        plt.close(fig)


# ---------------------------------------------------------------------------
# Package size chart
# ---------------------------------------------------------------------------

# Wheel sizes: (label, size_kb) — manylinux_2_17_x86_64, cp313
# Updated 2025-05-27 from PyPI
PACKAGE_SIZES = [
    ("whenever (pure python)", 116),
    ("whenever", 617),
    ("orjson", 131),
    ("msgspec", 220),
    ("pendulum", 341),
    ("arrow", 67),
    ("pydantic-core", 2048),
]


def plot_package_size(
    output: Path,
    theme: str,
) -> None:
    text_color = "#dde8f0" if theme == "dark" else "#333333"
    grid_color = "#3a4a5a" if theme == "dark" else "#e0e0e0"
    bar_color = "#E15759"

    labels = [p[0] for p in PACKAGE_SIZES]
    values_mb = [p[1] / 1024 for p in PACKAGE_SIZES]

    n = len(labels)
    y_pos = np.arange(n - 1, -1, -1, dtype=float)

    with plt.rc_context(_SVG_RC):
        fig, ax = plt.subplots(figsize=(5, 0.55 * n + 0.5))
        fig.patch.set_alpha(0)
        ax.set_facecolor("none")

        max_val = max(values_mb) if values_mb else 1.0

        for i, (val, y) in enumerate(zip(values_mb, y_pos)):
            ax.barh(
                y,
                val,
                height=0.55,
                color=bar_color,
                edgecolor="none",
                zorder=3,
            )
            # Format label
            if val >= 1.0:
                lbl = f"{val:.1f} MB"
            else:
                lbl = f"{int(val * 1024)} KB"
            ax.text(
                val + max_val * 0.02,
                y,
                lbl,
                va="center",
                ha="left",
                fontsize=9,
                color=text_color,
                zorder=4,
                clip_on=False,
            )

        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=9, color=text_color)
        ax.tick_params(axis="y", length=0, pad=6)

        ax.set_xlim(0, max_val * 1.35)
        ax.xaxis.set_major_formatter(
            mticker.FuncFormatter(lambda x, _: f"{x:.1f} MB")
        )
        ax.tick_params(axis="x", labelsize=8, colors=text_color, length=0)

        ax.grid(True, axis="x", color=grid_color, linewidth=0.6, zorder=0)
        ax.grid(False, axis="y")
        for spine in ax.spines.values():
            spine.set_visible(False)

        plt.tight_layout()
        _save_svg(fig, output)
        plt.close(fig)


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
        "--output",
        default=str(here / "charts"),
        metavar="DIR",
        help="output directory for SVG files (default: charts/)",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        metavar="PATH",
        help="Python interpreter to use for import measurements (default: sys.executable)",
    )
    parser.add_argument(
        "--skip-import",
        action="store_true",
        help="skip import time measurement (use cached/hardcoded values)",
    )
    args = parser.parse_args()
    out_dir = Path(args.output)

    # -- Import time --
    if not args.skip_import:
        python = args.python
        print(f"Measuring import times (using {python})…")
        times_ns: dict[str, float] = {}
        for mod in IMPORT_MODULES:
            t = measure_import(mod, python=python)
            times_ns[mod] = t
            print(f"  {mod:25s}: {t / 1e6:.2f} ms")

        print("\nGenerating import-time charts…")
        for theme in ("light", "dark"):
            plot_import_time(
                times_ns, out_dir / f"import-time-{theme}.svg", theme
            )

    # -- Package size --
    print("\nGenerating package-size charts…")
    for theme in ("light", "dark"):
        plot_package_size(out_dir / f"package-size-{theme}.svg", theme)

    print("\nDone.")


if __name__ == "__main__":
    main()
