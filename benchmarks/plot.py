import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from pathlib import Path

# ── Parameters & Labels ────────────────────────────────────────────────────────
sns.set_theme(style="whitegrid")
LABELS = {
    "libusb_native": "Libusb Native",
    "libusb_wasi":   "Libusb WASI",
    "rusb_native":   "Rusb Native",
    "rusb_wasi":     "Rusb WASI",
}

NAMES = ["libusb_native", "libusb_wasi", "rusb_native", "rusb_wasi"]
PALETTE = sns.color_palette("muted", n_colors=len(NAMES))
COLOR_MAP = {name: color for name, color in zip(NAMES, PALETTE)}

GROUPS = {
    "Libusb": ["libusb_native", "libusb_wasi"],
    "Rusb":   ["rusb_native",   "rusb_wasi"],
}

SCRIPT_DIR  = Path(__file__).parent
RESULTS_DIR = SCRIPT_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)


# ── Helper: gestylede boxplot met gekleurde uitschieters ─────────────────────
def styled_boxplot(ax, plot_data, plot_labels, colors,
                   title="", xlabel="Variant", ylabel="RTT (ms)"):
    bp = ax.boxplot(
        plot_data,
        tick_labels=plot_labels,
        vert=True,
        patch_artist=True,
        showfliers=True,
        flierprops={
            'marker': 'D', 'markersize': 6, 'alpha': 0.65,
            'markeredgecolor': 'white', 'markeredgewidth': 0.6,
        },
        medianprops={'linewidth': 2.5, 'color': '#111111'},
        boxprops={'linewidth': 1.2},
        whiskerprops={'linewidth': 1.5, 'color': '#444444'},
        capprops={'linewidth': 2.0, 'color': '#444444'},
        widths=0.55,
    )
    for patch, flier, color in zip(bp['boxes'], bp['fliers'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.78)
        patch.set_edgecolor('#333333')
        flier.set(markerfacecolor=color, markeredgecolor='white',
                  markeredgewidth=0.6, markersize=6, alpha=0.70)
    ax.set_title(title, fontsize=12, fontweight='bold', pad=8)
    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.grid(True, axis='y', linestyle='--', alpha=0.55)
    return bp


# ══════════════════════════════════════════════════════════════════════════════
# ── SECTIE 1: LATENCY ─────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

frames = []
for path in RESULTS_DIR.glob("rtt_results_latency_*.csv"):
    parts = path.stem.split("_")
    try:
        size    = int(parts[-1])
        variant = "_".join(parts[3:-1])
        df = pd.read_csv(path)
        df["variant"]    = variant
        df["size_bytes"] = size
        frames.append(df)
    except (ValueError, IndexError):
        continue

if not frames:
    print(f"No latency results found in {RESULTS_DIR}")
else:
    data = pd.concat(frames, ignore_index=True)

    # ── Plot 1: Gemiddelde RTT vs. Message Size ───────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 6))
    for i, name in enumerate(NAMES):
        subset = data[data["variant"] == name]
        if subset.empty:
            continue
        summary = (subset.groupby("size_bytes")["rtt_ms"]
                   .mean().reset_index().sort_values("size_bytes"))
        ax.plot(summary["size_bytes"], summary["rtt_ms"],
                marker="o", linewidth=2.5, label=LABELS[name], color=PALETTE[i])
    ax.set_xlabel("Message Size (bytes)", fontsize=12)
    ax.set_ylabel("Average RTT (ms)", fontsize=12)
    ax.set_title("USB Bulk Transfer Latency vs. Message Size", fontsize=14, fontweight='bold')
    ax.legend(title="Implementation", fontsize=10)
    ax.grid(True, linestyle='--', alpha=0.6)
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "rtt_vs_size_en.png", dpi=150, bbox_inches="tight")
    print(f"Saved: {RESULTS_DIR / 'rtt_vs_size_en.png'}")

    # ── Plot 2: Side-by-side boxplot per size (Libusb links, Rusb rechts) ─────
    sizes_present = sorted(data["size_bytes"].unique())
    for size in sizes_present:
        size_subset = data[data["size_bytes"] == size]
        fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
        fig.suptitle(f"Latency Comparison — Message Size: {size} bytes",
                     fontsize=14, fontweight='bold')
        col_groups = [("Libusb", ["libusb_native", "libusb_wasi"]),
                      ("Rusb",   ["rusb_native",   "rusb_wasi"])]
        for ax, (lib_name, variants) in zip(axes, col_groups):
            plot_data, plot_labels, colors = [], [], []
            for name in variants:
                vdata = size_subset[size_subset["variant"] == name]["rtt_ms"]
                if not vdata.empty:
                    plot_data.append(vdata)
                    plot_labels.append(LABELS.get(name, name))
                    colors.append(COLOR_MAP[name])
            if not plot_data:
                ax.set_visible(False)
                continue
            styled_boxplot(ax, plot_data, plot_labels, colors,
                           title=lib_name, xlabel="Variant", ylabel="RTT (ms)")
        fig.tight_layout()
        output_path = RESULTS_DIR / f"rtt_comparison_{size}b_en.png"
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"Saved: {output_path}")

    # ── Plot 3: Boxplot per size voor elke variant afzonderlijk ──────────────
    for i, name in enumerate(NAMES):
        subset = data[data["variant"] == name]
        if subset.empty:
            continue
        sizes  = sorted(subset["size_bytes"].unique())
        plot_data = [subset[subset["size_bytes"] == s]["rtt_ms"] for s in sizes]
        colors    = [COLOR_MAP[name]] * len(sizes)
        fig, ax = plt.subplots(figsize=(10, 6))
        styled_boxplot(ax, plot_data,
                       plot_labels=[str(s) for s in sizes], colors=colors,
                       title=f"Latency Distribution per Size — {LABELS.get(name, name)}",
                       xlabel="Message Size (bytes)", ylabel="RTT (ms)")
        fig.tight_layout()
        output_path = RESULTS_DIR / f"rtt_boxplot_sizes_{name}_en.png"
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"Saved: {output_path}")

    # ── Plot 4: WASI Overhead (%) t.o.v. Native ──────────────────────────────
    pairs = [("libusb_native", "libusb_wasi", "Libusb"),
             ("rusb_native",   "rusb_wasi",   "Rusb")]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    fig.suptitle("WebAssembly (WASI) Overhead vs. Native", fontsize=14, fontweight='bold')
    for ax, (native_key, wasi_key, lib_name) in zip(axes, pairs):
        sizes = sorted(data["size_bytes"].unique())
        overhead, valid_sizes = [], []
        for s in sizes:
            native_mean = data[(data["variant"] == native_key) & (data["size_bytes"] == s)]["rtt_ms"].mean()
            wasi_mean   = data[(data["variant"] == wasi_key)   & (data["size_bytes"] == s)]["rtt_ms"].mean()
            if pd.notna(native_mean) and pd.notna(wasi_mean) and native_mean > 0:
                overhead.append((wasi_mean - native_mean) / native_mean * 100)
                valid_sizes.append(s)
        bars = ax.bar([str(s) for s in valid_sizes], overhead,
                      color=[("tomato" if v > 0 else "steelblue") for v in overhead],
                      edgecolor='#333333', linewidth=0.8, alpha=0.85)
        ax.axhline(0, color='black', linewidth=1.0, linestyle='--')
        ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=9)
        ax.set_title(f"{lib_name}: WASI vs. Native", fontsize=12, fontweight='bold')
        ax.set_xlabel("Message Size (bytes)", fontsize=11)
        ax.set_ylabel("Overhead (%)", fontsize=11)
        ax.grid(True, axis='y', linestyle='--', alpha=0.5)
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "rtt_wasi_overhead_en.png", dpi=150, bbox_inches="tight")
    print(f"Saved: {RESULTS_DIR / 'rtt_wasi_overhead_en.png'}")

    # ── Plot 5: Faceted Grid — Native vs WASI, per library, per size ─────────
    n_sizes = len(sizes_present)
    fig, axes = plt.subplots(nrows=n_sizes, ncols=2,
                             figsize=(13, 4 * n_sizes), sharey='row')
    fig.suptitle("Native vs. WASI per Library & Message Size",
                 fontsize=14, fontweight='bold', y=1.01)
    if n_sizes == 1:
        axes = [axes]
    col_groups = [("Libusb", ["libusb_native", "libusb_wasi"]),
                  ("Rusb",   ["rusb_native",   "rusb_wasi"])]
    for row_idx, size in enumerate(sizes_present):
        size_subset = data[data["size_bytes"] == size]
        for col_idx, (lib_name, variants) in enumerate(col_groups):
            ax = axes[row_idx][col_idx]
            plot_data, plot_labels, colors = [], [], []
            for name in variants:
                vdata = size_subset[size_subset["variant"] == name]["rtt_ms"]
                if not vdata.empty:
                    plot_data.append(vdata)
                    plot_labels.append(LABELS.get(name, name))
                    colors.append(COLOR_MAP[name])
            if not plot_data:
                ax.set_visible(False)
                continue
            styled_boxplot(ax, plot_data, plot_labels, colors,
                           title=f"{lib_name} — {size} bytes",
                           xlabel="Variant", ylabel="RTT (ms)")
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "rtt_faceted_grid_en.png", dpi=150, bbox_inches="tight")
    print(f"Saved: {RESULTS_DIR / 'rtt_faceted_grid_en.png'}")

    # ── Plot 6: Heatmap — gemiddelde RTT per variant × size ──────────────────
    pivot = (data.groupby(["variant", "size_bytes"])["rtt_ms"]
             .mean().unstack(level="size_bytes").reindex(NAMES))
    pivot.index = [LABELS.get(n, n) for n in pivot.index]
    fig, ax = plt.subplots(figsize=(max(8, len(pivot.columns) * 1.4), 4))
    sns.heatmap(pivot, ax=ax, annot=True, fmt=".2f", cmap="YlOrRd",
                linewidths=0.5, linecolor='#cccccc',
                cbar_kws={"label": "Avg RTT (ms)"})
    ax.set_title("Gemiddelde RTT per Variant & Message Size", fontsize=13, fontweight='bold')
    ax.set_xlabel("Message Size (bytes)", fontsize=11)
    ax.set_ylabel("Implementatie", fontsize=11)
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0)
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "rtt_heatmap_en.png", dpi=150, bbox_inches="tight")
    print(f"Saved: {RESULTS_DIR / 'rtt_heatmap_en.png'}")

    # ── Plot 7: KDE per variant — alle sizes gestapeld ───────────────────────
    for i, name in enumerate(NAMES):
        subset = data[data["variant"] == name]
        if subset.empty:
            continue
        sizes  = sorted(subset["size_bytes"].unique())
        cmap   = plt.cm.viridis
        norm   = plt.Normalize(vmin=0, vmax=len(sizes) - 1)
        fig, ax = plt.subplots(figsize=(10, 6))
        max_clip = 0.0
        for j, size in enumerate(sizes):
            sdata = subset[subset["size_bytes"] == size]["rtt_ms"]
            if len(sdata) < 2:
                continue
            clip_max = sdata.mean() + sdata.std()
            max_clip = max(max_clip, clip_max)
            sns.kdeplot(sdata, ax=ax, label=f"{size} bytes",
                        color=cmap(norm(j)), linewidth=2.0,
                        fill=True, alpha=0.15, clip=(0, clip_max))
        ax.set_xlim(0, max_clip)
        ax.set_title(f"RTT-verdeling per Berichtgrootte — {LABELS.get(name, name)}",
                     fontsize=13, fontweight='bold')
        ax.set_xlabel("RTT (ms)", fontsize=11)
        ax.set_ylabel("Dichtheid", fontsize=11)
        ax.legend(title="Message Size", fontsize=9)
        ax.grid(True, linestyle='--', alpha=0.5)
        fig.tight_layout()
        output_path = RESULTS_DIR / f"rtt_kde_sizes_{name}_en.png"
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"Saved: {output_path}")

    # ── Plot 8: KDE Native vs WASI per library, per size (faceted) ───────────
    col_groups_kde = [("Libusb", "libusb_native", "libusb_wasi"),
                      ("Rusb",   "rusb_native",   "rusb_wasi")]
    for lib_name, native_key, wasi_key in col_groups_kde:
        sizes  = sorted(data["size_bytes"].unique())
        n      = len(sizes)
        ncols  = 2
        nrows  = (n + 1) // ncols
        fig, axes = plt.subplots(nrows, ncols, figsize=(13, 4 * nrows), sharey=False)
        fig.suptitle(f"{lib_name}: Native vs. WASI RTT-verdeling per Berichtgrootte",
                     fontsize=14, fontweight='bold')
        axes_flat = axes.flatten() if n > 1 else [axes]
        for idx, size in enumerate(sizes):
            ax = axes_flat[idx]
            size_subset = data[data["size_bytes"] == size]
            max_clip = 0.0
            for key, label_suffix in [(native_key, "Native"), (wasi_key, "WASI")]:
                sdata = size_subset[size_subset["variant"] == key]["rtt_ms"]
                if len(sdata) < 2:
                    continue
                clip_max = sdata.mean() + sdata.std()
                max_clip = max(max_clip, clip_max)
                sns.kdeplot(sdata, ax=ax, label=label_suffix, color=COLOR_MAP[key],
                            linewidth=2.2, fill=True, alpha=0.20, clip=(0, clip_max))
            if max_clip > 0:
                ax.set_xlim(0, max_clip)
            ax.set_title(f"{size} bytes", fontsize=11, fontweight='bold')
            ax.set_xlabel("RTT (ms)", fontsize=10)
            ax.set_ylabel("Dichtheid", fontsize=10)
            ax.legend(fontsize=9)
            ax.grid(True, linestyle='--', alpha=0.5)
        for idx in range(len(sizes), len(axes_flat)):
            axes_flat[idx].set_visible(False)
        fig.tight_layout()
        output_path = RESULTS_DIR / f"rtt_kde_native_vs_wasi_{lib_name.lower()}_en.png"
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"Saved: {output_path}")

    # ── Plot 9: KDE alle varianten per size ──────────────────────────────────
    for size in sizes_present:
        size_subset = data[data["size_bytes"] == size]
        fig, ax = plt.subplots(figsize=(10, 6))
        max_clip = 0.0
        for i, name in enumerate(NAMES):
            sdata = size_subset[size_subset["variant"] == name]["rtt_ms"]
            if len(sdata) < 2:
                continue
            clip_max = sdata.mean() + sdata.std()
            max_clip = max(max_clip, clip_max)
            sns.kdeplot(sdata, ax=ax, label=LABELS.get(name, name),
                        color=COLOR_MAP[name], linewidth=2.2,
                        fill=True, alpha=0.15, clip=(0, clip_max))
        if max_clip > 0:
            ax.set_xlim(0, max_clip)
        ax.set_title(f"RTT-verdeling alle Varianten — {size} bytes",
                     fontsize=13, fontweight='bold')
        ax.set_xlabel("RTT (ms)", fontsize=11)
        ax.set_ylabel("Dichtheid", fontsize=11)
        ax.legend(title="Implementatie", fontsize=9)
        ax.grid(True, linestyle='--', alpha=0.5)
        fig.tight_layout()
        output_path = RESULTS_DIR / f"rtt_kde_all_{size}b_en.png"
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"Saved: {output_path}")

    print("\nLatency visualizations complete.")


# ══════════════════════════════════════════════════════════════════════════════
# ── SECTIE 2: THROUGHPUT ──────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
# Bestandsformaat: throughput_results_{variant}_{N}MB.csv
# Kolommen:        run, direction, mb_per_sec
# Dimensies:       variant × size_mb × direction (write | read)

tframes = []
for path in RESULTS_DIR.glob("throughput_results_*.csv"):
    parts = path.stem.split("_")   # ["throughput","results", variant..., "{N}MB"]
    try:
        size_str = parts[-1]       # bijv. "64MB"
        if not size_str.endswith("MB"):
            continue
        size_mb = int(size_str[:-2])
        variant = "_".join(parts[2:-1])
        df = pd.read_csv(path)
        df["variant"] = variant
        df["size_mb"] = size_mb
        tframes.append(df)
    except (ValueError, IndexError):
        continue

if not tframes:
    print(f"No throughput results found in {RESULTS_DIR}")
else:
    tdata = pd.concat(tframes, ignore_index=True)
    tsizes_present = sorted(tdata["size_mb"].unique())
    DIRECTIONS = ["write", "read"]
    DIR_LABELS = {"write": "Write", "read": "Read"}

    # ── Plot T1: Gemiddelde MB/s vs Transfer Size — Write & Read ─────────────
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=False)
    fig.suptitle("USB Throughput vs. Transfer Size", fontsize=14, fontweight='bold')
    for ax, direction in zip(axes, DIRECTIONS):
        ddata = tdata[tdata["direction"] == direction]
        for i, name in enumerate(NAMES):
            subset = ddata[ddata["variant"] == name]
            if subset.empty:
                continue
            summary = (subset.groupby("size_mb")["mb_per_sec"]
                       .mean().reset_index().sort_values("size_mb"))
            ax.plot(summary["size_mb"], summary["mb_per_sec"],
                    marker="o", linewidth=2.5,
                    label=LABELS[name], color=PALETTE[i])
        ax.set_xlabel("Transfer Size (MB)", fontsize=12)
        ax.set_ylabel("Average Throughput (MB/s)", fontsize=12)
        ax.set_title(f"{DIR_LABELS[direction]}", fontsize=13, fontweight='bold')
        ax.legend(title="Implementation", fontsize=10)
        ax.grid(True, linestyle='--', alpha=0.6)
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "throughput_vs_size_en.png", dpi=150, bbox_inches="tight")
    print(f"Saved: {RESULTS_DIR / 'throughput_vs_size_en.png'}")

    # ── Plot T2: Side-by-side boxplot per size & direction ───────────────────
    for size in tsizes_present:
        size_subset = tdata[tdata["size_mb"] == size]
        fig, axes = plt.subplots(2, 2, figsize=(14, 11), sharey='row')
        fig.suptitle(f"Throughput Comparison — Transfer Size: {size} MB",
                     fontsize=14, fontweight='bold')
        col_groups = [("Libusb", ["libusb_native", "libusb_wasi"]),
                      ("Rusb",   ["rusb_native",   "rusb_wasi"])]
        for row_idx, direction in enumerate(DIRECTIONS):
            ddata = size_subset[size_subset["direction"] == direction]
            for col_idx, (lib_name, variants) in enumerate(col_groups):
                ax = axes[row_idx][col_idx]
                plot_data, plot_labels, colors = [], [], []
                for name in variants:
                    vdata = ddata[ddata["variant"] == name]["mb_per_sec"]
                    if not vdata.empty:
                        plot_data.append(vdata)
                        plot_labels.append(LABELS.get(name, name))
                        colors.append(COLOR_MAP[name])
                if not plot_data:
                    ax.set_visible(False)
                    continue
                styled_boxplot(ax, plot_data, plot_labels, colors,
                               title=f"{lib_name} — {DIR_LABELS[direction]}",
                               xlabel="Variant", ylabel="MB/s")
        fig.tight_layout()
        output_path = RESULTS_DIR / f"throughput_comparison_{size}MB_en.png"
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"Saved: {output_path}")

    # ── Plot T3: Boxplot per size, per variant, per direction ─────────────────
    for i, name in enumerate(NAMES):
        subset = tdata[tdata["variant"] == name]
        if subset.empty:
            continue
        fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=False)
        fig.suptitle(f"Throughput Distribution per Size — {LABELS.get(name, name)}",
                     fontsize=13, fontweight='bold')
        for ax, direction in zip(axes, DIRECTIONS):
            ddata  = subset[subset["direction"] == direction]
            sizes  = sorted(ddata["size_mb"].unique())
            plot_data = [ddata[ddata["size_mb"] == s]["mb_per_sec"] for s in sizes]
            colors    = [COLOR_MAP[name]] * len(sizes)
            styled_boxplot(ax, plot_data,
                           plot_labels=[f"{s} MB" for s in sizes], colors=colors,
                           title=DIR_LABELS[direction],
                           xlabel="Transfer Size (MB)", ylabel="MB/s")
        fig.tight_layout()
        output_path = RESULTS_DIR / f"throughput_boxplot_sizes_{name}_en.png"
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"Saved: {output_path}")

    # ── Plot T4: WASI Overhead (%) t.o.v. Native, per direction ──────────────
    pairs = [("libusb_native", "libusb_wasi", "Libusb"),
             ("rusb_native",   "rusb_wasi",   "Rusb")]
    fig, axes = plt.subplots(2, 2, figsize=(13, 10), sharey='row')
    fig.suptitle("Throughput: WASI Overhead vs. Native", fontsize=14, fontweight='bold')
    for row_idx, direction in enumerate(DIRECTIONS):
        ddata = tdata[tdata["direction"] == direction]
        for col_idx, (native_key, wasi_key, lib_name) in enumerate(pairs):
            ax = axes[row_idx][col_idx]
            sizes = sorted(tdata["size_mb"].unique())
            overhead, valid_sizes = [], []
            for s in sizes:
                native_mean = ddata[(ddata["variant"] == native_key) & (ddata["size_mb"] == s)]["mb_per_sec"].mean()
                wasi_mean   = ddata[(ddata["variant"] == wasi_key)   & (ddata["size_mb"] == s)]["mb_per_sec"].mean()
                if pd.notna(native_mean) and pd.notna(wasi_mean) and native_mean > 0:
                    overhead.append((wasi_mean - native_mean) / native_mean * 100)
                    valid_sizes.append(s)
            bars = ax.bar([f"{s} MB" for s in valid_sizes], overhead,
                          color=[("tomato" if v < 0 else "steelblue") for v in overhead],
                          edgecolor='#333333', linewidth=0.8, alpha=0.85)
            ax.axhline(0, color='black', linewidth=1.0, linestyle='--')
            ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=9)
            ax.set_title(f"{lib_name} — {DIR_LABELS[direction]}", fontsize=12, fontweight='bold')
            ax.set_xlabel("Transfer Size (MB)", fontsize=11)
            ax.set_ylabel("Overhead (%)", fontsize=11)
            ax.grid(True, axis='y', linestyle='--', alpha=0.5)
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "throughput_wasi_overhead_en.png", dpi=150, bbox_inches="tight")
    print(f"Saved: {RESULTS_DIR / 'throughput_wasi_overhead_en.png'}")

    # ── Plot T5: Heatmap — gemiddelde MB/s per variant × size, write & read ──
    fig, axes = plt.subplots(1, 2, figsize=(max(10, len(tsizes_present) * 1.8), 5))
    fig.suptitle("Gemiddelde Throughput per Variant & Transfer Size (MB/s)",
                 fontsize=13, fontweight='bold')
    for ax, direction in zip(axes, DIRECTIONS):
        ddata = tdata[tdata["direction"] == direction]
        pivot = (ddata.groupby(["variant", "size_mb"])["mb_per_sec"]
                 .mean().unstack(level="size_mb").reindex(NAMES))
        pivot.index = [LABELS.get(n, n) for n in pivot.index]
        pivot.columns = [f"{c} MB" for c in pivot.columns]
        sns.heatmap(pivot, ax=ax, annot=True, fmt=".1f", cmap="YlGn",
                    linewidths=0.5, linecolor='#cccccc',
                    cbar_kws={"label": "Avg MB/s"})
        ax.set_title(DIR_LABELS[direction], fontsize=12, fontweight='bold')
        ax.set_xlabel("Transfer Size", fontsize=11)
        ax.set_ylabel("Implementatie", fontsize=11)
        ax.set_yticklabels(ax.get_yticklabels(), rotation=0)
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "throughput_heatmap_en.png", dpi=150, bbox_inches="tight")
    print(f"Saved: {RESULTS_DIR / 'throughput_heatmap_en.png'}")

    # ── Plot T6: KDE per variant — alle sizes, per direction ─────────────────
    for i, name in enumerate(NAMES):
        subset = tdata[tdata["variant"] == name]
        if subset.empty:
            continue
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.suptitle(f"Throughput-verdeling per Schrijfgrootte — {LABELS.get(name, name)}",
                     fontsize=13, fontweight='bold')
        cmap = plt.cm.viridis
        for ax, direction in zip(axes, DIRECTIONS):
            ddata = subset[subset["direction"] == direction]
            sizes = sorted(ddata["size_mb"].unique())
            norm  = plt.Normalize(vmin=0, vmax=max(len(sizes) - 1, 1))
            max_clip = 0.0
            for j, size in enumerate(sizes):
                sdata = ddata[ddata["size_mb"] == size]["mb_per_sec"]
                if len(sdata) < 2:
                    continue
                clip_max = sdata.mean() + sdata.std()
                max_clip = max(max_clip, clip_max)
                sns.kdeplot(sdata, ax=ax, label=f"{size} MB",
                            color=cmap(norm(j)), linewidth=2.0,
                            fill=True, alpha=0.15, clip=(0, clip_max))
            if max_clip > 0:
                ax.set_xlim(0, max_clip)
            ax.set_title(DIR_LABELS[direction], fontsize=12, fontweight='bold')
            ax.set_xlabel("MB/s", fontsize=11)
            ax.set_ylabel("Dichtheid", fontsize=11)
            ax.legend(title="Transfer Size", fontsize=9)
            ax.grid(True, linestyle='--', alpha=0.5)
        fig.tight_layout()
        output_path = RESULTS_DIR / f"throughput_kde_sizes_{name}_en.png"
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"Saved: {output_path}")

    # ── Plot T7: KDE alle varianten per size & direction ─────────────────────
    for size in tsizes_present:
        size_subset = tdata[tdata["size_mb"] == size]
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.suptitle(f"Throughput-verdeling alle Varianten — {size} MB",
                     fontsize=13, fontweight='bold')
        for ax, direction in zip(axes, DIRECTIONS):
            ddata = size_subset[size_subset["direction"] == direction]
            max_clip = 0.0
            for i, name in enumerate(NAMES):
                sdata = ddata[ddata["variant"] == name]["mb_per_sec"]
                if len(sdata) < 2:
                    continue
                clip_max = sdata.mean() + sdata.std()
                max_clip = max(max_clip, clip_max)
                sns.kdeplot(sdata, ax=ax, label=LABELS.get(name, name),
                            color=COLOR_MAP[name], linewidth=2.2,
                            fill=True, alpha=0.15, clip=(0, clip_max))
            if max_clip > 0:
                ax.set_xlim(0, max_clip)
            ax.set_title(DIR_LABELS[direction], fontsize=12, fontweight='bold')
            ax.set_xlabel("MB/s", fontsize=11)
            ax.set_ylabel("Dichtheid", fontsize=11)
            ax.legend(title="Implementatie", fontsize=9)
            ax.grid(True, linestyle='--', alpha=0.5)
        fig.tight_layout()
        output_path = RESULTS_DIR / f"throughput_kde_all_{size}MB_en.png"
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"Saved: {output_path}")

    print("\nThroughput visualizations complete.")


# ══════════════════════════════════════════════════════════════════════════════
# ── SECTIE 3: INIT-TIJD (libusb_init + enumerate + open + claim)  ─────────────
# ══════════════════════════════════════════════════════════════════════════════
# CSVs: results/init_results_<variant>_<devicelabel>.csv
# Kolommen: iteration, init_ms, enumerate_ms, open_ms, claim_ms, teardown_ms, total_ms

init_frames = []
for path in RESULTS_DIR.glob("init_results_*.csv"):
    # bestandsnaam: init_results_<variant>_<label>.csv
    # <variant> is "libusb_native" of "libusb_wasi"
    stem = path.stem  # init_results_libusb_native_usb3ss_sandisk
    parts = stem.split("_")
    if len(parts) < 5:
        continue
    # Neem "libusb_native" / "libusb_wasi" als variant (eerste 2 tokens na "init_results")
    variant = "_".join(parts[2:4])
    label = "_".join(parts[4:])
    if variant not in LABELS:
        continue
    try:
        df = pd.read_csv(path)
    except Exception:
        continue
    df["variant"] = variant
    df["device"] = label
    init_frames.append(df)

if init_frames:
    df_init = pd.concat(init_frames, ignore_index=True)
    phases = ["init_ms", "enumerate_ms", "open_ms", "claim_ms", "teardown_ms", "total_ms"]

    for device in df_init["device"].unique():
        sub = df_init[df_init["device"] == device]
        fig, axes = plt.subplots(2, 3, figsize=(14, 8))
        axes = axes.flatten()
        for i, phase in enumerate(phases):
            ax = axes[i]
            data = []
            labels = []
            colors = []
            for variant in ["libusb_native", "libusb_wasi"]:
                v = sub[sub["variant"] == variant][phase].dropna()
                if len(v) == 0:
                    continue
                data.append(v.values)
                labels.append(LABELS[variant])
                colors.append(COLOR_MAP[variant])
            if not data:
                ax.set_visible(False)
                continue
            styled_boxplot(ax, data, labels, colors,
                           title=f"{phase.replace('_ms','').capitalize()}",
                           xlabel="", ylabel="Duur (ms)")
        fig.suptitle(f"USB-stack init-overhead — {device}",
                     fontsize=13, fontweight='bold')
        fig.tight_layout()
        out = RESULTS_DIR / f"plot_init_{device}.png"
        fig.savefig(out, dpi=140, bbox_inches='tight')
        plt.close(fig)
        print(f"Saved: {out}")

    # Tabel: mediaan per fase per variant per device
    print("\nInit-tijd (mediaan, ms):")
    summary = (df_init.groupby(["device", "variant"])[phases]
                      .median()
                      .round(3))
    print(summary.to_string())
else:
    print("\n(init_results_*.csv niet gevonden — sla init-plot over)")

print("\nAll visualizations complete. Plots saved in the results/ directory.")