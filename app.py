from pathlib import Path
import matplotlib.pyplot as plt
import pandas as pd
import wntr
import webbrowser

# =========================
# UBAH DI SINI
# =========================
INP_PATH = Path(r"C:\Users\msndh\Downloads\MAGANG SCTK\GIS_SCTK\Jaringan Eksisting PT SCTK - New.inp")
PIPE_TO_CLOSE = "P1106"
TIME_SEC = 3600
TOP_N = 20

M_PER_BAR = 10.2
OK_BAR_MIN = 3.0
VERY_LOW_MAX = 1.0


def m_to_bar(m):
    return m / M_PER_BAR


def fmt_m_bar(m):
    return f"{m:.1f} m ≈ {m_to_bar(m):.2f} bar"


def service_status(p_bar):
    if pd.isna(p_bar):
        return "N/A"
    if p_bar <= 0:
        return "MATI TOTAL"
    elif p_bar < VERY_LOW_MAX:
        return "SANGAT RENDAH (0-1 bar)"
    elif p_bar < OK_BAR_MIN:
        return f"RENDAH (1-{OK_BAR_MIN:g} bar)"
    return f"OK (>= {OK_BAR_MIN:g} bar)"


def run_pressure_at_time(wn, time_sec):
    sim = wntr.sim.EpanetSimulator(wn)
    results = sim.run_sim()

    times = results.node["pressure"].index
    used_time = time_sec if time_sec in times else int(times[0])

    p_raw = results.node["pressure"].loc[used_time].copy()
    p_clean = p_raw.copy()
    p_clean[p_clean < 0] = 0

    return p_raw, p_clean, used_time


def plot_service_categories(wn, p_closed_bar_clean, title):
    xs, ys, statuses = [], [], []

    for n in wn.node_name_list:
        node = wn.get_node(n)
        if not hasattr(node, "coordinates") or node.coordinates is None:
            continue
        x, y = node.coordinates
        xs.append(x)
        ys.append(y)
        statuses.append(service_status(float(p_closed_bar_clean.get(n, float("nan")))))

    dfp = pd.DataFrame({"x": xs, "y": ys, "status": statuses})

    fig, ax = plt.subplots(figsize=(10, 7))
    wntr.graphics.plot_network(wn, node_attribute=None, node_size=0,
                               title=title, show_plot=False, ax=ax)

    color_map = {
        "MATI TOTAL": "red",
        "SANGAT RENDAH (0-1 bar)": "orange",
        f"RENDAH (1-{OK_BAR_MIN:g} bar)": "yellow",
        f"OK (>= {OK_BAR_MIN:g} bar)": "green",
    }

    for cat, color in color_map.items():
        sub = dfp[dfp["status"] == cat]
        if len(sub):
            ax.scatter(sub["x"], sub["y"], s=18, c=color, label=cat, zorder=5)

    ax.legend(loc="best")
    ax.set_xticks([])
    ax.set_yticks([])
    plt.tight_layout()
    return fig  # <-- penting biar bisa save


def main():
    if not INP_PATH.exists():
        raise FileNotFoundError(f"INP tidak ditemukan: {INP_PATH}")

    outdir = Path("outputs")
    outdir.mkdir(parents=True, exist_ok=True)

    # ===== BASE =====
    wn_base = wntr.network.WaterNetworkModel(str(INP_PATH))
    p_base_raw, p_base_clean, used_time = run_pressure_at_time(wn_base, TIME_SEC)

    # ===== CLOSED =====
    wn_closed = wntr.network.WaterNetworkModel(str(INP_PATH))
    wn_closed.get_link(PIPE_TO_CLOSE).initial_status = "Closed"
    p_closed_raw, p_closed_clean, _ = run_pressure_at_time(wn_closed, used_time)

    # ===== ANALISIS =====
    dp_m = p_base_clean - p_closed_clean
    p_base_bar = p_base_clean.apply(m_to_bar)
    p_closed_bar = p_closed_clean.apply(m_to_bar)
    dp_bar = dp_m.apply(m_to_bar)

    # ===== REPORT =====
    df = pd.DataFrame({
        "P_base_m": p_base_clean,
        "P_closed_m": p_closed_clean,
        "Drop_m": dp_m,
        "P_base_bar": p_base_bar,
        "P_closed_bar": p_closed_bar,
        "Drop_bar": dp_bar,
    })

    df["P_closed (m ≈ bar)"] = df["P_closed_m"].apply(fmt_m_bar)
    df["Drop (m ≈ bar)"] = df["Drop_m"].apply(fmt_m_bar)
    df["Status"] = df["P_closed_bar"].apply(service_status)

    top_impacted = df.sort_values("Drop_m", ascending=False).head(TOP_N)

    # simpan CSV biar tombol download jalan
    df.to_csv(outdir / "service_report.csv", index=True)

    print("\n=== SERVICE IMPACT REPORT ===")
    print(f"Pipa ditutup : {PIPE_TO_CLOSE}")
    print(f"Waktu        : {used_time}s ({used_time/3600:.2f} jam)")
    print(f"Rule OK      : OK jika >= {OK_BAR_MIN:g} bar")
    print("Catatan      : Pressure negatif dari simulator di-set 0 untuk analisis layanan.\n")
    print(top_impacted[["P_closed (m ≈ bar)", "Drop (m ≈ bar)", "Status"]])

    # ===== FIGURE 1 =====
    fig1, axes = plt.subplots(1, 3, figsize=(18, 5))
    wntr.graphics.plot_network(wn_base, p_base_clean, node_size=20,
                               title=f"Pressure BASE (t={used_time}s)",
                               show_plot=False, ax=axes[0])
    wntr.graphics.plot_network(wn_closed, p_closed_clean, node_size=20,
                               title=f"Pressure CLOSED '{PIPE_TO_CLOSE}' (t={used_time}s)",
                               show_plot=False, ax=axes[1])
    wntr.graphics.plot_network(wn_closed, dp_m, node_size=20,
                               title="ΔPressure = BASE - CLOSED",
                               show_plot=False, ax=axes[2])
    plt.tight_layout()
    fig1.savefig(outdir / "pressure_maps.png", dpi=200, bbox_inches="tight")

    # ===== FIGURE 2 =====
    fig2 = plot_service_categories(
        wn_closed,
        p_closed_bar,
        title=(
            f"Service Impact Map AFTER closing '{PIPE_TO_CLOSE}' (t={used_time}s)\n"
            f"Red=MATI, Orange=0–1 bar, Yellow=1–{OK_BAR_MIN:g} bar, Green>= {OK_BAR_MIN:g} bar"
        )
    )
    fig2.savefig(outdir / "service_impact.png", dpi=200, bbox_inches="tight")

    # ===== DASHBOARD HTML (di dalam main biar used_time ada) =====
    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Water Network Impact Dashboard</title>
<style>
body {{ font-family: Arial; background:#f4f6f8; margin:20px; }}
button {{ padding:10px 16px; margin:5px; cursor:pointer; }}
img {{ max-width:100%; display:none; margin-top:15px; border:1px solid #aaa; }}
.card {{ background:white; padding:20px; border-radius:8px; }}
</style>
</head>

<body>
<div class="card">
<h2>Service Impact Dashboard</h2>

<p><b>Pipe closed:</b> {PIPE_TO_CLOSE} <br>
<b>Time:</b> {used_time/3600:.2f} hours</p>

<button onclick="showImage('p1')">Pressure Analysis</button>
<button onclick="showImage('p2')">Service Impact Map</button>
<button onclick="window.open('outputs/service_report.csv')">Download Report</button>

<img id="p1" src="outputs/pressure_maps.png">
<img id="p2" src="outputs/service_impact.png">
</div>

<script>
function showImage(id){{
    document.getElementById('p1').style.display='none';
    document.getElementById('p2').style.display='none';
    document.getElementById(id).style.display='block';
}}
</script>
</body>
</html>
"""

    dashboard_path = Path("dashboard.html")
    dashboard_path.write_text(html, encoding="utf-8")
    webbrowser.open(dashboard_path.resolve().as_uri())

    plt.show()


if __name__ == "__main__":
    main()