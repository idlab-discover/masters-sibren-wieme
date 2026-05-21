#!/usr/bin/env python3
"""
bench/analyze.py — WASI-USB thesis data analysis & figures

Usage:
    python3 bench/analyze.py <results-dir> [--plots <out-dir>] [--check-only]

Arguments:
    results-dir    Directory produced by bench/run.sh (contains *.csv files)
    --plots DIR    Write PNG/PDF figures to DIR (default: <results-dir>/plots/)
    --check-only   Only run correctness checks, no plots
    --format FMT   Figure format: png (default) or pdf

Output:
    1. Correctness table — per workload: are W-bulk checksums
       consistent across conditions?
    2. Throughput bar chart — MB/s per condition × workload
    3. RTT violin plot — RTT distribution per condition (all three workloads)
    4. Startup table — first-transfer latency (iteration 0) per condition
    5. Memory bar chart — RSS peak + guest linear memory
    6. Wrapper-overhead figure — C3 vs C5 RTT comparison
    7. Statistical tests — Mann-Whitney U + Cliff's delta + Shapiro-Wilk
       normality test for key pairs

Note: plot_total_runtime() is defined but not called from main(). The
total_runtime_ns CSV column is retained as operational metadata but is
not plotted in the thesis (it adds no information beyond per-transfer RTT).

Requires: pandas, matplotlib, seaborn, scipy, numpy
Install:  pip install pandas matplotlib seaborn scipy numpy
"""

import argparse
import re
import sys
import os
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")   # non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import seaborn as sns
from scipy import stats


# ── Palette & style ──────────────────────────────────────────────────────────

CONDITION_ORDER = ["native-libusb", "wasi-libusb", "native-rusb", "wasi-rusb", "wasi-raw-wit"]
CONDITION_LABELS = {
    "native-libusb": "C1\nnative-libusb",
    "wasi-libusb":   "C2\nwasi-libusb",
    "native-rusb":   "C3\nnative-rusb",
    "wasi-rusb":     "C4\nwasi-rusb",
    "wasi-raw-wit":  "C5\nwasi-raw-wit",
}
CONDITION_COLORS = {
    "native-libusb": "#2196F3",   # blue
    "wasi-libusb":   "#64B5F6",   # light blue
    "native-rusb":   "#43A047",   # green
    "wasi-rusb":     "#81C784",   # mid green
    "wasi-raw-wit":  "#A5D6A7",   # light green
}

WORKLOAD_ORDER = ["bulk", "ctrl", "int"]
WORKLOAD_LABELS = {
    "bulk": "Bulk\n(SCSI READ, 64 KiB)",
    "ctrl": "Control\n(GET_DESCRIPTOR, 18 B)",
    "int":  "Interrupt\n(HID IN, 64 B)",
}

sns.set_theme(style="whitegrid", font_scale=1.1)


# ── CSV loading ───────────────────────────────────────────────────────────────

CSV_DTYPES = {
    "condition":         str,
    "workload":          str,
    "iteration":         "int64",
    "bytes":             "int64",
    "duration_ns":       "int64",
    "rss_peak_kb":       "int64",
    "guest_mem_bytes":   "float64",
    "checksum_hex":      str,
    "total_runtime_ns":  "float64",   # wall-clock guest total (optional)
    "notes":             str,
}


def load_results(results_dir: Path) -> pd.DataFrame:
    """Load all CSV files in results_dir into a single DataFrame."""
    frames = []
    for csv_path in sorted(results_dir.glob("*.csv")):
        if csv_path.name == "meta.txt":
            continue
        try:
            df = pd.read_csv(csv_path, dtype=str)
            # Coerce numeric columns
            for col, dtype in CSV_DTYPES.items():
                if col in df.columns and dtype != str:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            frames.append(df)
        except Exception as e:
            print(f"  [warn] Could not load {csv_path.name}: {e}", file=sys.stderr)

    if not frames:
        sys.exit(f"No CSV files found in {results_dir}")

    df = pd.concat(frames, ignore_index=True)
    # Derived columns
    df["rtt_us"]    = df["duration_ns"] / 1_000.0
    df["rtt_ms"]    = df["duration_ns"] / 1_000_000.0
    df["mb_s"]      = (df["bytes"] / 1_048_576.0) / (df["duration_ns"] / 1e9)

    # Order categorical columns for consistent plots
    df["condition"] = pd.Categorical(
        df["condition"], categories=CONDITION_ORDER, ordered=True
    )
    df["workload"] = pd.Categorical(
        df["workload"], categories=WORKLOAD_ORDER, ordered=True
    )
    return df


# ── Statistics helpers ────────────────────────────────────────────────────────

def cliffs_delta(a: np.ndarray, b: np.ndarray) -> float:
    """Cliff's delta effect size (−1 … +1)."""
    n1, n2 = len(a), len(b)
    if n1 == 0 or n2 == 0:
        return float("nan")
    dominance = sum(1 if ai > bi else (-1 if ai < bi else 0)
                    for ai in a for bi in b)
    return dominance / (n1 * n2)


def mannwhitney(a: np.ndarray, b: np.ndarray):
    """Mann-Whitney U test; returns (U, p-value, Cliff's delta)."""
    if len(a) < 2 or len(b) < 2:
        return float("nan"), float("nan"), float("nan")
    u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
    d = cliffs_delta(a, b)
    return u, p, d


def effect_label(d: float) -> str:
    ad = abs(d)
    if ad < 0.147:  return "negligible"
    if ad < 0.330:  return "small"
    if ad < 0.474:  return "medium"
    return "large"


def summary_stats(series: pd.Series) -> dict:
    s = series.dropna()
    return {
        "n":      len(s),
        "median": s.median(),
        "mean":   s.mean(),
        "std":    s.std(),
        "p5":     s.quantile(0.05),
        "p95":    s.quantile(0.95),
        "iqr":    s.quantile(0.75) - s.quantile(0.25),
    }


# ── 1. Correctness table ──────────────────────────────────────────────────────

def check_correctness(df: pd.DataFrame) -> bool:
    print("\n━━━ 1. Correctness (checksum consistency) ━━━━━━━━━━━━━━━━━━━━━━━━━━")
    ok = True
    for wl in ["bulk"]:
        sub = df[(df["workload"] == wl) & df["checksum_hex"].notna() &
                 (df["checksum_hex"] != "")]
        if sub.empty:
            print(f"  {wl:6s}  — no checksum data")
            continue
        unique = sub["checksum_hex"].nunique()
        conds  = sub["condition"].unique().tolist()
        status = "✓ PASS" if unique == 1 else f"✗ FAIL ({unique} distinct checksums)"
        print(f"  {wl:6s}  {status}   conditions: {conds}")
        if unique == 1:
            sample = sub["checksum_hex"].iloc[0]
            print(f"         SHA-256 (all conditions): {sample}")
        if unique != 1:
            ok = False
    for wl in ["ctrl", "int"]:
        sub = df[df["workload"] == wl]
        if sub.empty:
            print(f"  {wl:6s}  — no data")
        else:
            print(f"  {wl:6s}  — no checksum (expected)   n={len(sub)}")
    return ok


# ── Axis-clipping helper ──────────────────────────────────────────────────────

def _clip_xlim(ax, series: pd.Series, cond_series: pd.Series,
               left: float = 0.0, margin: float = 0.05):
    """Set x-axis to [left, max(mean+std) * (1+margin)] to clip outlier tails.

    User spec: "from 0 to mean+std of the largest condition".
    Applied to all violin plots so extreme rare events do not compress the
    core distribution into a thin spike.
    """
    per_cond_stats = series.groupby(cond_series).agg(["mean", "std"]).dropna()
    if per_cond_stats.empty:
        return
    clip_max = (per_cond_stats["mean"] + per_cond_stats["std"]).max()
    ax.set_xlim(left=left, right=clip_max * (1 + margin))


# ── 2. Throughput violin plot (W-bulk only) ───────────────────────────────────

def plot_throughput(df: pd.DataFrame, out_dir: Path, fmt: str):
    """Horizontal violin plot of per-transfer throughput distribution for W-bulk.

    Shows the full MB/s distribution per condition (C1–C5), not just
    median ± std.  Throughput (MB/s) is on the X-axis; conditions on the Y-axis.
    One figure, 7×5 inches.
    """
    sub = df[df["workload"] == "bulk"].copy()
    if sub.empty:
        print("  [skip] throughput: no bulk data")
        return

    conds_present = [c for c in CONDITION_ORDER
                     if c in sub["condition"].cat.categories
                     and not sub[sub["condition"] == c]["mb_s"].dropna().empty]
    if not conds_present:
        print("  [skip] throughput: no mb_s values")
        return

    plot_data = sub[sub["condition"].isin(conds_present)].copy()

    fig, ax = plt.subplots(figsize=(7, 5))
    sns.violinplot(
        data=plot_data,
        x="mb_s", y="condition",
        order=conds_present,
        orient="h",
        palette={c: CONDITION_COLORS.get(c, "#888") for c in conds_present},
        inner="quartile",
        ax=ax,
    )
    ax.set_yticklabels([CONDITION_LABELS.get(c, c) for c in conds_present],
                       fontsize=9)
    _clip_xlim(ax, plot_data["mb_s"], plot_data["condition"])
    # Annotate median value next to each violin's median line
    for i, c in enumerate(conds_present):
        vals = plot_data[plot_data["condition"] == c]["mb_s"].dropna()
        if vals.empty:
            continue
        med = vals.median()
        if not np.isnan(med):
            ax.text(med, i, f"  {med:.1f}", va="center", ha="left",
                    fontsize=8, color="black")
    ax.set_xlabel("Throughput (MB/s)")
    ax.set_ylabel("")
    ax.set_title("W-bulk throughput distribution per condition\n"
                 "(SCSI READ, 64 KiB transfers)", fontsize=12)
    ax.grid(axis="x", linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)

    fig.tight_layout()
    _save(fig, out_dir / f"throughput.{fmt}")
    print(f"  [plot] throughput → throughput.{fmt}")


# ── 3. RTT violin plots — one figure per workload ────────────────────────────

def plot_rtt(df: pd.DataFrame, out_dir: Path, fmt: str):
    """One violin figure per workload for the RTT distribution (all conditions).

    Figures are saved as rtt_violin_bulk.{fmt}, rtt_violin_ctrl.{fmt},
    rtt_violin_int.{fmt}.  Each is 7×6 inches so the violins are readable.
    Scales differ between workloads (W-ctrl ~8–16 µs, W-int ~4000 µs,
    W-bulk ~1–2 ms), so combining them in a single figure would produce
    misleadingly small violins for the low-latency workloads.
    """
    workloads = [w for w in WORKLOAD_ORDER if w in df["workload"].values]
    if not workloads:
        print("  [skip] RTT violin: no data")
        return

    for wl in workloads:
        wl_data = df[df["workload"] == wl].copy()
        conds_present = [c for c in CONDITION_ORDER
                         if c in wl_data["condition"].cat.categories
                         and wl_data[wl_data["condition"] == c].shape[0] > 0]
        if not conds_present:
            print(f"  [skip] rtt_violin_{wl}: no data")
            continue

        plot_data = wl_data[wl_data["condition"].isin(conds_present)].copy()
        y_col, y_label = _workload_unit(wl)

        fig, ax = plt.subplots(figsize=(7, 5))
        sns.violinplot(
            data=plot_data,
            x=y_col, y="condition",
            order=conds_present,
            orient="h",
            palette={c: CONDITION_COLORS.get(c, "#888") for c in conds_present},
            inner="quartile",
            ax=ax,
        )
        ax.set_yticklabels([CONDITION_LABELS.get(c, c) for c in conds_present],
                           fontsize=9)
        _clip_xlim(ax, plot_data[y_col], plot_data["condition"])
        wl_label = WORKLOAD_LABELS.get(wl, wl).replace("\n", " ")
        ax.set_title(f"RTT distribution — {wl_label}", fontsize=12)
        ax.set_xlabel(y_label)
        ax.set_ylabel("")
        ax.grid(axis="x", linestyle="--", alpha=0.4)
        ax.set_axisbelow(True)

        fig.tight_layout()
        fname = f"rtt_violin_{wl}"
        _save(fig, out_dir / f"{fname}.{fmt}")
        print(f"  [plot] RTT violin ({wl}) → {fname}.{fmt}")


# ── 4. Total runtime bar chart ────────────────────────────────────────────────

def plot_total_runtime(df: pd.DataFrame, out_dir: Path, fmt: str):
    """Bar chart of total wall-clock guest runtime per condition × workload.

    Prefers the ``total_runtime_ns`` column (emitted by benchmark binaries
    when BENCH_START_NS / BENCH_END_NS prints are present and captured by
    run.sh).  Falls back to summing per-iteration ``duration_ns`` values when
    that column is absent or all-NaN, which gives the total time spent inside
    USB transfers (excludes loop bookkeeping overhead, but is a close proxy).

    Units: milliseconds (ms).
    """
    workloads = [w for w in WORKLOAD_ORDER if w in df["workload"].values]
    if not workloads:
        print("  [skip] total runtime: no data")
        return

    has_wall = ("total_runtime_ns" in df.columns and
                df["total_runtime_ns"].notna().any())
    src_label = "wall-clock (BENCH_START/END)" if has_wall else "sum of transfer durations"

    rows = []
    for wl in workloads:
        for cond in CONDITION_ORDER:
            sub = df[(df["workload"] == wl) & (df["condition"] == cond)]
            if sub.empty:
                continue
            if has_wall:
                # take the last (or only) reported total_runtime_ns per run
                val_ns = sub["total_runtime_ns"].dropna()
                if val_ns.empty:
                    val_ms = sub["duration_ns"].sum() / 1e6
                else:
                    val_ms = float(val_ns.iloc[-1]) / 1e6
            else:
                val_ms = sub["duration_ns"].sum() / 1e6
            rows.append({"workload": wl, "condition": cond, "total_ms": val_ms})

    if not rows:
        print("  [skip] total runtime: could not compute values")
        return

    agg = pd.DataFrame(rows)
    n_wl = len(workloads)
    fig, axes = plt.subplots(1, n_wl, figsize=(4 * n_wl, 5), sharey=False)
    if n_wl == 1:
        axes = [axes]

    for ax, wl in zip(axes, workloads):
        wl_data = agg[agg["workload"] == wl]
        conds   = [c for c in CONDITION_ORDER if c in wl_data["condition"].values]
        x       = np.arange(len(conds))
        vals    = [float(wl_data.loc[wl_data["condition"] == c, "total_ms"].iloc[0])
                   for c in conds]
        colors  = [CONDITION_COLORS.get(c, "#888") for c in conds]

        bars = ax.bar(x, vals, color=colors, edgecolor="white", linewidth=0.5)
        ax.set_xticks(x)
        ax.set_xticklabels([CONDITION_LABELS.get(c, c) for c in conds], fontsize=9)
        ax.set_title(WORKLOAD_LABELS.get(wl, wl), fontsize=11)
        ax.set_ylabel("Total runtime (ms)")
        ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.0f"))

        for bar, val in zip(bars, vals):
            h = bar.get_height()
            ax.annotate(f"{val:.0f}",
                        (bar.get_x() + bar.get_width() / 2, h),
                        ha="center", va="bottom", fontsize=9,
                        xytext=(0, 2), textcoords="offset points")

    fig.suptitle(f"Total guest runtime per condition ({src_label})",
                 fontsize=12, y=1.01)
    fig.tight_layout()
    _save(fig, out_dir / f"total_runtime.{fmt}")
    print(f"  [plot] total runtime → total_runtime.{fmt}")


# ── 5. Startup latency (iteration 0) ─────────────────────────────────────────

def print_startup(df: pd.DataFrame):
    print("\n━━━ 5. Startup latency (iteration 0, per condition × workload) ━━━━━━")
    first = df[df["iteration"] == 0].copy()
    if first.empty:
        print("  No iteration-0 data found")
        return

    tbl = (first.groupby(["workload", "condition"], observed=True)["rtt_us"]
                .first()
                .unstack("condition")
                .reindex(columns=[c for c in CONDITION_ORDER
                                  if c in first["condition"].cat.categories]))
    print(tbl.to_string(float_format=lambda x: f"{x:9.1f} µs"))


# ── 6. Memory bar chart ───────────────────────────────────────────────────────

# Short condition codes used in resources_<cond>_<wl>.csv filenames.
_COND_SHORT = {
    "C1": "native-libusb",
    "C2": "wasi-libusb",
    "C3": "native-rusb",
    "C4": "wasi-rusb",
    "C5": "wasi-raw-wit",
}


def load_external_rss(results_dir: Path) -> dict:
    """Return peak RSS (MiB) per (condition, workload) from resources_*.csv.

    run.sh writes resources_<Cx>_<wl>.csv using ps -o rss=, which reports KiB
    on both Linux and macOS.  Values are converted to MiB here.  Returns an
    empty dict when no resource files exist (e.g. older result sets).
    """
    peaks: dict = {}
    for path in sorted(results_dir.glob("resources_C[0-9]_*.csv")):
        stem = path.stem[len("resources_"):]   # "C2_ctrl"
        parts = stem.split("_", 1)
        if len(parts) != 2:
            continue
        short, wl = parts
        cond = _COND_SHORT.get(short)
        if cond is None:
            continue
        try:
            rdf = pd.read_csv(path)
            if "rss_kb" in rdf.columns and not rdf.empty:
                peaks[(cond, wl)] = float(rdf["rss_kb"].max()) / 1024.0
        except Exception:
            pass
    return peaks


def load_rusage(results_dir: Path) -> dict:
    """Parse per-cell rusage_C*_*.txt files written by /usr/bin/time -l (macOS)
    or /usr/bin/time -v (Linux GNU).

    Returns {(cond, wl): {"rss_mib": float|None,
                          "vol_ctx": int|None,
                          "invol_ctx": int|None}}.

    Unit normalization:
      macOS BSD time (-l): RSS in bytes  → divide by 1024² for MiB.
      Linux GNU time (-v): RSS in KiB    → divide by 1024 for MiB.
    """
    data: dict = {}
    for path in sorted(results_dir.glob("rusage_C[0-9]_*.txt")):
        stem = path.stem[len("rusage_"):]   # "C2_ctrl"
        parts = stem.split("_", 1)
        if len(parts) != 2:
            continue
        short, wl = parts
        cond = _COND_SHORT.get(short)
        if cond is None:
            continue
        try:
            text = path.read_text(errors="replace")
        except Exception:
            continue

        rss_mib = vol_ctx = invol_ctx = None
        for raw in text.splitlines():
            line = raw.strip()
            # macOS: "1122304  maximum resident set size"
            m = re.match(r'^(\d+)\s+maximum resident set size$', line)
            if m:
                rss_mib = int(m.group(1)) / (1024 * 1024)
                continue
            # Linux: "Maximum resident set size (kbytes): 1096"
            m = re.search(r'Maximum resident set size \(kbytes\):\s*(\d+)', line)
            if m:
                rss_mib = int(m.group(1)) / 1024.0
                continue
            # macOS: "123  voluntary context switches"
            m = re.match(r'^(\d+)\s+voluntary context switches$', line)
            if m:
                vol_ctx = int(m.group(1))
                continue
            # Linux: "Voluntary context switches: 123"
            m = re.search(r'Voluntary context switches:\s*(\d+)', line)
            if m:
                vol_ctx = int(m.group(1))
                continue
            # macOS: "45  involuntary context switches"
            m = re.match(r'^(\d+)\s+involuntary context switches$', line)
            if m:
                invol_ctx = int(m.group(1))
                continue
            # Linux: "Involuntary context switches: 45"
            m = re.search(r'Involuntary context switches:\s*(\d+)', line)
            if m:
                invol_ctx = int(m.group(1))
                continue

        if rss_mib is not None or vol_ctx is not None or invol_ctx is not None:
            data[(cond, wl)] = {
                "rss_mib":   rss_mib,
                "vol_ctx":   vol_ctx,
                "invol_ctx": invol_ctx,
            }
    return data


def plot_memory(df: pd.DataFrame, out_dir: Path, fmt: str,
                results_dir: Path | None = None):
    """Grouped bar chart of peak host RSS and guest linear memory per condition.

    RSS source priority (most to least reliable):
      1. /usr/bin/time -l/-v rusage files (rusage_*.txt) — kernel-measured at exit.
      2. 200 ms ps poller (resources_*.csv) — fallback for older result sets.
      3. In-process rss_peak_kb column — unreliable for WASI (getrusage returns 0).

    Bars are side-by-side (grouped) so both values can be read independently.
    Host RSS includes the Wasmtime runtime; guest linear memory is the portion
    Wasmtime allocates for the Wasm linear address space (~45 MiB per component,
    allocated at instantiation).  C1–C3 (native conditions) have no guest memory.

    Note: C1–C5 are benchmark *conditions*, not the C programming language.
    """
    rusage_data = load_rusage(results_dir) if results_dir is not None else {}
    ext_rss     = load_external_rss(results_dir) if results_dir is not None else {}

    last = (df.sort_values("iteration")
              .groupby(["workload", "condition"], observed=True)
              .last()
              .reset_index())

    workloads = [w for w in WORKLOAD_ORDER if w in last["workload"].values]
    n_wl = len(workloads)
    if n_wl == 0:
        print("  [skip] memory: no data")
        return

    bar_w = 0.35
    fig, axes = plt.subplots(1, n_wl, figsize=(5 * n_wl, 5), sharey=False)
    if n_wl == 1:
        axes = [axes]

    for ax, wl in zip(axes, workloads):
        wl_data = last[last["workload"] == wl]
        conds   = [c for c in CONDITION_ORDER if c in wl_data["condition"].values]
        x       = np.arange(len(conds))

        rss_vals   = []
        guest_vals = []
        for c in conds:
            # ── host RSS ─────────────────────────────────────────────────────
            if (c, wl) in rusage_data and rusage_data[(c, wl)]["rss_mib"] is not None:
                rss = rusage_data[(c, wl)]["rss_mib"]
            elif (c, wl) in ext_rss:
                rss = ext_rss[(c, wl)]
            else:
                row = wl_data.loc[wl_data["condition"] == c, "rss_peak_kb"]
                rss = float(row.iloc[0]) / 1024.0 if not row.empty else 0.0
            rss_vals.append(rss)

            # ── guest linear memory ──────────────────────────────────────────
            gm_row = wl_data.loc[wl_data["condition"] == c, "guest_mem_bytes"]
            gm = (float(gm_row.iloc[0]) / (1024 * 1024)
                  if (not gm_row.empty
                      and pd.notna(gm_row.iloc[0])
                      and gm_row.iloc[0] > 0)
                  else 0.0)
            guest_vals.append(gm)

        rss_arr   = np.array(rss_vals)
        guest_arr = np.array(guest_vals)

        bars_rss   = ax.bar(x - bar_w / 2, rss_arr,   bar_w,
                            label="Host RSS",      color="#5C6BC0", edgecolor="white")
        bars_guest = ax.bar(x + bar_w / 2, guest_arr, bar_w,
                            label="Guest linear",  color="#EF9A9A", edgecolor="white")

        # Value annotations
        for bar in list(bars_rss) + list(bars_guest):
            h = bar.get_height()
            if h > 0.1:
                ax.annotate(f"{h:.0f}",
                            (bar.get_x() + bar.get_width() / 2, h),
                            ha="center", va="bottom", fontsize=7,
                            xytext=(0, 2), textcoords="offset points")

        ax.set_xticks(x)
        ax.set_xticklabels([CONDITION_LABELS.get(c, c) for c in conds],
                           fontsize=8, rotation=45, ha="right")
        ax.set_title(WORKLOAD_LABELS.get(wl, wl), fontsize=11)
        ax.set_ylabel("Memory (MiB)")
        if ax == axes[0]:
            ax.legend(fontsize=8)

    if rusage_data:
        src = "/usr/bin/time (kernel peak)"
    elif ext_rss:
        src = "ps poller peak"
    else:
        src = "in-process (unreliable for WASI)"
    fig.suptitle(
        f"Peak memory per condition ({src})\n"
        "Left bar = host RSS; right bar = guest linear memory.  "
        "C1–C5 are benchmark conditions.",
        fontsize=10, y=1.03,
    )
    fig.tight_layout()
    _save(fig, out_dir / f"memory.{fmt}")
    print(f"  [plot] memory → memory.{fmt}")


# ── 7. Wrapper-overhead figure (C3 vs C5) ────────────────────────────────────

def plot_wrapper_overhead(df: pd.DataFrame, out_dir: Path, fmt: str):
    sub = df[df["condition"].isin(["native-rusb", "wasi-raw-wit"])].copy()
    if sub.empty:
        print("  [skip] wrapper overhead: no C3/C5 data")
        return

    workloads = [w for w in WORKLOAD_ORDER if w in sub["workload"].values]
    n_wl = len(workloads)
    fig, axes = plt.subplots(1, n_wl, figsize=(4 * n_wl, 5), sharey=False)
    if n_wl == 1:
        axes = [axes]

    for ax, wl in zip(axes, workloads):
        wl_data = sub[sub["workload"] == wl]
        for cond in ["native-rusb", "wasi-raw-wit"]:
            s = wl_data[wl_data["condition"] == cond]["rtt_us"].dropna().values
            if len(s) == 0:
                continue
            xs = np.sort(s)
            ys = np.arange(1, len(xs) + 1) / len(xs)
            ax.plot(xs, ys, label=CONDITION_LABELS.get(cond, cond),
                    color=CONDITION_COLORS.get(cond, "#888"), linewidth=1.5)
        ax.set_title(WORKLOAD_LABELS.get(wl, wl), fontsize=11)
        ax.set_xlabel("RTT (µs)")
        ax.set_ylabel("CDF")
        ax.legend(fontsize=8)

    fig.suptitle("Wrapper overhead: C3 (native-rusb) vs C5 (wasi-raw-wit)\n"
                 "CDF of per-transfer RTT", fontsize=12, y=1.02)
    fig.tight_layout()
    _save(fig, out_dir / f"wrapper_overhead.{fmt}")
    print(f"  [plot] wrapper overhead → wrapper_overhead.{fmt}")


# ── 7b. Single-comparison overhead figures ───────────────────────────────────
#
# Each figure shows exactly one A-vs-B comparison, with the three workloads
# side-by-side as subplots.  Absolute median RTT is drawn as bars with values
# on top and ±1σ (standard deviation) error bars.  The relative %-delta is
# intentionally omitted: it is misleading for W-ctrl because the native
# baseline benefits from macOS IOKit descriptor caching, making any relative
# figure unrepresentative.

def _workload_unit(wl: str):
    """Return (y_column, y_label) for the given workload."""
    if wl == "bulk":
        return "rtt_ms", "RTT (ms)"
    return "rtt_us", "RTT (µs)"


def plot_pair_violin_split(df: pd.DataFrame, out_dir: Path, fmt: str,
                           cond_a: str, cond_b: str,
                           base_title: str, fname_base: str):
    """One violin figure *per workload* for an A-vs-B comparison.

    Replaces the old side-by-side bar chart: each workload gets its own
    figure so that y-axis scales are not misleadingly shared (W-ctrl is
    ~8–16 µs, W-int is ~4000 µs, W-bulk is ~1–2 ms — completely different
    scales).  Violin plots show the full RTT distribution, not just
    median ± std.
    """
    workloads = [w for w in WORKLOAD_ORDER if w in df["workload"].values]
    for wl in workloads:
        sub = df[df["workload"] == wl]
        a = sub[sub["condition"] == cond_a]["rtt_us"].dropna()
        b = sub[sub["condition"] == cond_b]["rtt_us"].dropna()
        if a.empty or b.empty:
            print(f"  [skip] {fname_base}_{wl}: insufficient data")
            continue

        y_col, y_label = _workload_unit(wl)

        plot_data = sub[sub["condition"].isin([cond_a, cond_b])].copy()
        conds_here = [c for c in [cond_a, cond_b]
                      if c in plot_data["condition"].values]

        fig, ax = plt.subplots(figsize=(6, 4))
        sns.violinplot(
            data=plot_data,
            x=y_col, y="condition",
            order=conds_here,
            orient="h",
            palette={c: CONDITION_COLORS.get(c, "#888") for c in conds_here},
            inner="quartile",
            ax=ax,
        )
        ax.set_yticklabels(
            [CONDITION_LABELS.get(c, c) for c in conds_here],
            fontsize=10,
        )
        _clip_xlim(ax, plot_data[y_col], plot_data["condition"])
        ax.set_xlabel(y_label)
        ax.set_ylabel("")
        wl_label = WORKLOAD_LABELS.get(wl, wl).replace("\n", " ")
        ax.set_title(f"{base_title}\n{wl_label}", fontsize=12)
        ax.grid(axis="x", linestyle="--", alpha=0.4)
        ax.set_axisbelow(True)

        fig.tight_layout()
        out_name = f"{fname_base}_{wl}"
        _save(fig, out_dir / f"{out_name}.{fmt}")
        print(f"  [plot] {out_name} → {out_name}.{fmt}")


def plot_all_pairs(df: pd.DataFrame, out_dir: Path, fmt: str):
    """Per-workload violin figures for Q1 (libusb), Q1 (rusb), and Q2."""
    plot_pair_violin_split(df, out_dir, fmt,
                           "native-libusb", "wasi-libusb",
                           "Q1a — WASI overhead: libusb path (C1 vs C2)",
                           "q1_libusb_overhead")
    plot_pair_violin_split(df, out_dir, fmt,
                           "native-rusb", "wasi-rusb",
                           "Q1b — WASI overhead: rusb path (C3 vs C4)",
                           "q1_rusb_overhead")
    plot_pair_violin_split(df, out_dir, fmt,
                           "wasi-libusb", "wasi-rusb",
                           "Q2 — libusb vs rusb inside the sandbox (C2 vs C4)",
                           "q2_backend_in_sandbox")


# ── 7c. LaTeX summary table export (three separate sub-tables) ───────────────

def export_summary_latex(df: pd.DataFrame, out_dir: Path):
    """Write three LaTeX tabular environments — one per workload — with columns
    median, mean, stdev, max (RTT in µs).  For W-bulk, throughput (MB/s) is
    appended as an extra column.

    Each sub-table is written to its own file:
      summary_table_bulk.tex, summary_table_ctrl.tex, summary_table_int.tex
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for wl in WORKLOAD_ORDER:
        sub = df[df["workload"] == wl]
        if sub.empty:
            continue

        rows = []
        for cond in CONDITION_ORDER:
            s = sub[sub["condition"] == cond]["rtt_us"].dropna()
            if s.empty:
                continue
            row = {
                "condition": cond,
                "n":         len(s),
                "median":    s.median(),
                "mean":      s.mean(),
                "stdev":     s.std(),
                "max":       s.max(),
            }
            if wl == "bulk":
                t = sub[sub["condition"] == cond]["mb_s"].dropna()
                row["mb_s"] = t.median() if not t.empty else float("nan")
            rows.append(row)

        if not rows:
            continue

        fname = out_dir / f"summary_table_{wl}.tex"
        with fname.open("w") as f:
            f.write(f"% Auto-generated by analyze.py — do not edit by hand.\n")
            f.write(f"% Workload: {wl}   RTT in µs.\n")
            if wl == "bulk":
                f.write("\\begin{tabular}{lrrrrrr}\n")
                f.write("\\toprule\n")
                f.write("Condition & $n$ & median (µs) & mean (µs) & std (µs) "
                        "& max (µs) & median (MB/s) \\\\\n")
            else:
                f.write("\\begin{tabular}{lrrrrr}\n")
                f.write("\\toprule\n")
                f.write("Condition & $n$ & median (µs) & mean (µs) & std (µs) "
                        "& max (µs) \\\\\n")
            f.write("\\midrule\n")
            for r in rows:
                line = (f"{r['condition']} & {r['n']:d} & "
                        f"{r['median']:.1f} & {r['mean']:.1f} & "
                        f"{r['stdev']:.1f} & {r['max']:.1f}")
                if wl == "bulk":
                    mb = r.get("mb_s", float("nan"))
                    line += f" & {mb:.1f}" if not np.isnan(mb) else " & —"
                line += " \\\\\n"
                f.write(line)
            f.write("\\bottomrule\n")
            f.write("\\end{tabular}\n")
        print(f"  [latex] summary table ({wl}) → {fname.name}")


# ── 7d. LaTeX export of statistical test tables (for appendix) ──────────────

def export_stats_latex(df: pd.DataFrame, out_dir: Path):
    """Write two appendix tables to LaTeX files:
      stats_shapiro.tex   — Shapiro-Wilk normality test (all 15 cells)
      stats_mannwhitney.tex — Mann-Whitney U + Cliff's delta (6 pairs × 3 workloads)
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Shapiro-Wilk table ────────────────────────────────────────────────────
    n_tests = sum(
        1 for wl in WORKLOAD_ORDER for cond in CONDITION_ORDER
        if not df[(df["workload"] == wl) & (df["condition"] == cond)]["rtt_us"].dropna().empty
    )
    bonferroni = 0.05 / max(n_tests, 1)

    fname_sw = out_dir / "stats_shapiro.tex"
    with fname_sw.open("w") as f:
        f.write("% Auto-generated by analyze.py — do not edit by hand.\n")
        f.write(f"% Bonferroni-corrected α = 0.05/{n_tests} ≈ {bonferroni:.2e}\n")
        f.write("\\begin{tabular}{llrrrr}\n")
        f.write("\\toprule\n")
        f.write("Workload & Condition & $n$ & $W$ & $p$ & Normal? \\\\\n")
        f.write("\\midrule\n")
        for wl in WORKLOAD_ORDER:
            wl_label = {"bulk": "W-bulk", "ctrl": "W-ctrl", "int": "W-int"}.get(wl, wl)
            first = True
            for cond in CONDITION_ORDER:
                s = df[(df["workload"] == wl) & (df["condition"] == cond)]["rtt_us"].dropna()
                if len(s) < 3:
                    continue
                sample = s.values if len(s) <= 5000 else np.random.choice(s.values, 5000, replace=False)
                w_stat, p_val = stats.shapiro(sample)
                normal_str = "yes" if p_val >= bonferroni else "no"
                wl_col = wl_label if first else ""
                first = False
                p_str = f"$< 10^{{{int(np.floor(np.log10(p_val + 1e-300)))}}}$" if p_val < 1e-3 else f"{p_val:.4f}"
                f.write(f"{wl_col} & {cond} & {len(s):d} & "
                        f"{w_stat:.4f} & {p_str} & {normal_str} \\\\\n")
        f.write("\\bottomrule\n")
        f.write("\\end{tabular}\n")
    print(f"  [latex] Shapiro-Wilk table → {fname_sw.name}")

    # ── Mann-Whitney + Cliff's delta table ────────────────────────────────────
    pair_labels = [
        ("native-libusb", "wasi-libusb",  "C1 vs C2", "WASI overhead (libusb)"),
        ("native-rusb",   "wasi-rusb",    "C3 vs C4", "WASI overhead (rusb)"),
        ("native-rusb",   "wasi-raw-wit", "C3 vs C5", "WASI overhead (raw WIT)"),
        ("wasi-rusb",     "wasi-raw-wit", "C4 vs C5", "rusb wrapper cost"),
        ("native-libusb", "native-rusb",  "C1 vs C3", "Language effect (native)"),
        ("wasi-libusb",   "wasi-raw-wit", "C2 vs C5", "Language effect (WASI)"),
    ]

    fname_mw = out_dir / "stats_mannwhitney.tex"
    with fname_mw.open("w") as f:
        f.write("% Auto-generated by analyze.py — do not edit by hand.\n")
        f.write("\\begin{tabular}{lllrrrrl}\n")
        f.write("\\toprule\n")
        f.write("Workload & Pair & Description & $n_a$ & $n_b$ & "
                "$U$ & $p$ & $\\delta$ (effect) \\\\\n")
        f.write("\\midrule\n")
        for wl in WORKLOAD_ORDER:
            sub = df[df["workload"] == wl]
            wl_label = {"bulk": "W-bulk", "ctrl": "W-ctrl", "int": "W-int"}.get(wl, wl)
            first = True
            for cond_a, cond_b, pair_str, desc in pair_labels:
                a = sub[sub["condition"] == cond_a]["rtt_us"].dropna().values
                b = sub[sub["condition"] == cond_b]["rtt_us"].dropna().values
                if len(a) < 2 or len(b) < 2:
                    continue
                u, p, d = mannwhitney(a, b)
                eff = effect_label(d)
                if np.isnan(p):
                    p_str = "n/a"
                elif p < 1e-10:
                    p_str = f"$< 10^{{{int(np.floor(np.log10(p + 1e-300)))}}}$"
                elif p < 0.001:
                    p_str = f"{p:.2e}"
                else:
                    p_str = f"{p:.4f}"
                wl_col = wl_label if first else ""
                first = False
                d_str = f"{d:+.3f} ({eff})"
                f.write(f"{wl_col} & {pair_str} & {desc} & "
                        f"{len(a):d} & {len(b):d} & "
                        f"{u:.0f} & {p_str} & {d_str} \\\\\n")
            if wl != WORKLOAD_ORDER[-1]:
                f.write("\\midrule\n")
        f.write("\\bottomrule\n")
        f.write("\\end{tabular}\n")
    print(f"  [latex] Mann-Whitney table → {fname_mw.name}")


# ── 8. Statistical tests ──────────────────────────────────────────────────────

PAIRS = [
    ("native-libusb", "wasi-libusb",  "C1↔C2  WASI cost (C)"),
    ("native-rusb",   "wasi-rusb",    "C3↔C4  rusb→WASM cost"),
    ("native-rusb",   "wasi-raw-wit", "C3↔C5  WASI cost (Rust, raw WIT)"),
    ("wasi-rusb",     "wasi-raw-wit", "C4↔C5  rusb wrapper overhead"),
    ("native-libusb", "native-rusb",  "C1↔C3  Language effect (native)"),
    ("wasi-libusb",   "wasi-raw-wit", "C2↔C5  Language effect (WASI)"),
]


def print_shapiro(df: pd.DataFrame):
    """Shapiro-Wilk normality test per condition × workload.

    Justification for non-parametric tests: if distributions are significantly
    non-normal (p < 0.001 after Bonferroni correction), Mann-Whitney U +
    Cliff's delta are the appropriate statistics; otherwise a t-test and
    Cohen's d would be equally valid.
    """
    print("\n━━━ Normality tests (Shapiro-Wilk, H₀: data is normally distributed) ━")
    n_tests = sum(
        1
        for wl in WORKLOAD_ORDER
        for cond in CONDITION_ORDER
        if not df[(df["workload"] == wl) & (df["condition"] == cond)]["rtt_us"].dropna().empty
    )
    bonferroni = 0.05 / max(n_tests, 1)
    print(f"  Bonferroni-corrected α = 0.05 / {n_tests} = {bonferroni:.2e}\n")
    for wl in WORKLOAD_ORDER:
        print(f"  Workload: {wl}")
        print(f"  {'Condition':<18} {'n':>6} {'W':>10} {'p':>12}  normal?")
        print("  " + "─" * 55)
        for cond in CONDITION_ORDER:
            s = df[(df["workload"] == wl) & (df["condition"] == cond)]["rtt_us"].dropna()
            if len(s) < 3:
                continue
            # Shapiro-Wilk is reliable for n ≤ 5000; subsample if larger
            sample = s.values if len(s) <= 5000 else np.random.choice(s.values, 5000, replace=False)
            w, p = stats.shapiro(sample)
            normal = "yes" if p >= bonferroni else "NO"
            print(f"  {cond:<18} {len(s):>6} {w:>10.4f} {p:>12.2e}  {normal}")
        print()


def print_stats(df: pd.DataFrame):
    print("\n━━━ 8. Statistical tests (Mann-Whitney U + Cliff's delta) ━━━━━━━━━━")
    for wl in WORKLOAD_ORDER:
        sub = df[df["workload"] == wl]
        if sub.empty:
            continue
        print(f"\n  Workload: {wl}")
        print(f"  {'Comparison':<38} {'n_a':>6} {'n_b':>6} "
              f"{'U':>10} {'p':>10} {'delta':>8}  effect")
        print("  " + "─" * 90)
        for cond_a, cond_b, label in PAIRS:
            a = sub[sub["condition"] == cond_a]["rtt_us"].dropna().values
            b = sub[sub["condition"] == cond_b]["rtt_us"].dropna().values
            if len(a) < 2 or len(b) < 2:
                print(f"  {label:<38}  — insufficient data")
                continue
            u, p, d = mannwhitney(a, b)
            eff = effect_label(d)
            p_str = f"{p:.2e}" if not np.isnan(p) else "n/a"
            print(f"  {label:<38} {len(a):>6} {len(b):>6} "
                  f"{u:>10.0f} {p_str:>10} {d:>+8.3f}  {eff}")


# ── Summary table ─────────────────────────────────────────────────────────────

def print_summary(df: pd.DataFrame):
    print("\n━━━ Descriptive statistics (RTT µs, per workload × condition) ━━━━━━")
    for wl in WORKLOAD_ORDER:
        sub = df[df["workload"] == wl]
        if sub.empty:
            continue
        print(f"\n  {wl}:")
        print(f"  {'condition':<18} {'n':>6} {'median':>9} {'mean':>9} "
              f"{'std':>9} {'p5':>9} {'p95':>9}")
        print("  " + "─" * 70)
        for cond in CONDITION_ORDER:
            s = sub[sub["condition"] == cond]["rtt_us"].dropna()
            if s.empty:
                continue
            st = summary_stats(s)
            print(f"  {cond:<18} {st['n']:>6} {st['median']:>9.1f} "
                  f"{st['mean']:>9.1f} {st['std']:>9.1f} "
                  f"{st['p5']:>9.1f} {st['p95']:>9.1f}")


# ── A4. Outlier rate report ───────────────────────────────────────────────────

def print_outlier_rates(df: pd.DataFrame):
    """Report the percentage of outliers (|x − median| > 1.5 × IQR) per cell.

    Mirrors Leroy's methodology (he reported ~2–3% outlier rate and attributed
    the excess to USB scheduling jitter).  Outliers are NOT removed from the
    data — this function only reports their prevalence.  The x-axis clip in
    violin plots is a display-only operation; the data underneath is unfiltered.
    """
    print("\n━━━ Outlier rates per cell  (|x−median| > 1.5×IQR, data kept) ━━━━━━")
    print(f"  {'Workload':<8} {'Condition':<18} {'n':>6} {'outliers':>9} {'rate':>8}")
    print("  " + "─" * 58)
    for wl in WORKLOAD_ORDER:
        for cond in CONDITION_ORDER:
            s = df[(df["workload"] == wl) & (df["condition"] == cond)]["rtt_us"].dropna()
            if len(s) < 4:
                continue
            q1, q3 = s.quantile(0.25), s.quantile(0.75)
            iqr = q3 - q1
            if iqr == 0:
                continue
            median    = s.median()
            n_out     = int(((s - median).abs() > 1.5 * iqr).sum())
            rate      = 100.0 * n_out / len(s)
            print(f"  {wl:<8} {cond:<18} {len(s):>6} {n_out:>9} {rate:>7.2f}%")


# ── A3. Context-switch comparison (C1 vs C2 W-ctrl) ──────────────────────────

def print_ctx_switch_comparison(rusage: dict):
    """Print per-cell context-switch totals from /usr/bin/time rusage files.

    Compares C1 (native-libusb) vs C2 (wasi-libusb) on W-ctrl to substantiate
    (or refute) the Tokio-scheduling attribution for the bimodal C2 distribution.
    Excess involuntary context switches in C2 ≈ second-mode transfer count would
    support the hypothesis.  Reported as supporting evidence, not per-transfer proof.
    """
    print("\n━━━ Context switches from /usr/bin/time (C1 vs C2, W-ctrl) ━━━━━━━━━")
    if not rusage:
        print("  No rusage_*.txt data found — re-run with updated run.sh to collect.")
        return
    print(f"  {'Condition':<18} {'vol. ctx sw':>12} {'invol. ctx sw':>14} {'RSS (MiB)':>10}")
    print("  " + "─" * 58)
    for label, key in [("C1 native-libusb", ("native-libusb", "ctrl")),
                       ("C2 wasi-libusb",   ("wasi-libusb",   "ctrl"))]:
        rec = rusage.get(key)
        if rec is None:
            print(f"  {label:<18} {'—':>12} {'—':>14} {'—':>10}")
            continue
        vol   = rec.get("vol_ctx")
        invol = rec.get("invol_ctx")
        rss   = rec.get("rss_mib")
        v_s = f"{vol:12d}"   if vol   is not None else "         n/a"
        i_s = f"{invol:14d}" if invol is not None else "           n/a"
        r_s = f"{rss:10.1f}" if rss   is not None else "       n/a"
        print(f"  {label:<18} {v_s} {i_s} {r_s}")
    c1 = rusage.get(("native-libusb", "ctrl"))
    c2 = rusage.get(("wasi-libusb",   "ctrl"))
    if c1 and c2:
        i1, i2 = c1.get("invol_ctx"), c2.get("invol_ctx")
        if i1 is not None and i2 is not None:
            excess = i2 - i1
            sign   = "+" if excess >= 0 else ""
            print(f"\n  Excess invol. ctx switches C2 − C1: {sign}{excess}")
            if excess > 0:
                print("  → supports Tokio-scheduling attribution for bimodal C2")
            else:
                print("  → does not support context-switch attribution; other cause likely")


# ── Save helper ───────────────────────────────────────────────────────────────

def _save(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", dpi=150)
    plt.close(fig)


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="WASI-USB benchmark analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("results_dir", help="Directory with CSV files from bench/run.sh")
    p.add_argument("--plots", metavar="DIR",
                   help="Output directory for figures (default: <results_dir>/plots)")
    p.add_argument("--check-only", action="store_true",
                   help="Only run correctness checks, skip plots")
    p.add_argument("--format", default="png", choices=["png", "pdf"],
                   metavar="FMT", dest="fmt",
                   help="Figure file format (default: png)")
    return p.parse_args()


def main():
    args = parse_args()
    results_dir = Path(args.results_dir).resolve()
    if not results_dir.is_dir():
        sys.exit(f"results_dir not found: {results_dir}")

    plots_dir = Path(args.plots).resolve() if args.plots \
                else results_dir / "plots"

    print(f"Loading results from: {results_dir}")
    df = load_results(results_dir)
    print(f"  Loaded {len(df)} rows  "
          f"({df['condition'].nunique()} conditions × "
          f"{df['workload'].nunique()} workloads)")

    # Load rusage data (from /usr/bin/time -l/-v files if present)
    rusage_data = load_rusage(results_dir)

    # 1. Correctness
    check_correctness(df)

    # 5. Startup table (text only)
    print_startup(df)

    # Normality test (justifies Mann-Whitney U choice)
    print_shapiro(df)

    # 8. Statistical tests (text only)
    print_summary(df)
    print_stats(df)

    # A4. Outlier rate report
    print_outlier_rates(df)

    # A3. Context-switch comparison (C1 vs C2 W-ctrl)
    print_ctx_switch_comparison(rusage_data)

    if args.check_only:
        print("\n[--check-only] Skipping plots.")
        return

    print(f"\nWriting figures to: {plots_dir}")
    plots_dir.mkdir(parents=True, exist_ok=True)

    # 2. Throughput
    plot_throughput(df, plots_dir, args.fmt)

    # 3. RTT violins (all three workloads)
    plot_rtt(df, plots_dir, args.fmt)

    # 6. Memory (uses rusage as primary RSS source)
    plot_memory(df, plots_dir, args.fmt, results_dir=results_dir)

    # 7. Wrapper overhead
    plot_wrapper_overhead(df, plots_dir, args.fmt)

    # 7b. Single-comparison overhead figures (Q1a, Q1b, Q2)
    plot_all_pairs(df, plots_dir, args.fmt)

    # 7c. LaTeX summary tables (one per workload, stdev instead of p95/p99)
    export_summary_latex(df, plots_dir)

    # 7d. LaTeX appendix tables (Shapiro-Wilk + Mann-Whitney)
    export_stats_latex(df, plots_dir)

    print(f"\n✓ Done — figures in {plots_dir}")


if __name__ == "__main__":
    main()
