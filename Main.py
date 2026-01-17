from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import wntr

# =========================
# UBAH DI SINI
# =========================
INP_PATH = Path(r"C:\Users\msndh\Downloads\MAGANG SCTK\GIS_SCTK\Jaringan Eksisting PT SCTK - New.inp")
PIPE_TO_CLOSE = "P1106"   # ganti nama pipa
TIME_SEC = 3600           # waktu evaluasi (detik)
TOP_N = 20                # ringkasan tabel

# Konversi: 1 bar ≈ 10.2 mH2O
M_PER_BAR = 10.2

# Threshold bisnis
OK_BAR_MIN = 3.0          # OK kalau >= 3 bar
VERY_LOW_MAX = 1.0        # sangat rendah kalau < 1 bar


def m_to_bar(m: float) -> float:
    return m / M_PER_BAR


def fmt_m_bar(m: float) -> str:
    return f"{m:.1f} m \u2248 {m_to_bar(m):.2f} bar"


def service_status(p_bar: float) -> str:
    if pd.isna(p_bar):
        return "N/A"
    if p_bar <= 0:
        return "MATI TOTAL"
    elif p_bar < VERY_LOW_MAX:
        return "SANGAT RENDAH (0-1 bar)"
    elif p_bar < OK_BAR_MIN:
        return f"RENDAH (1-{OK_BAR_MIN:g} bar)"
    return f"OK (>= {OK_BAR_MIN:g} bar)"


def run_pressure_at_time(wn: wntr.network.WaterNetworkModel, time_sec: int):
    """
    Run EPANET simulation and return:
      - p_raw   : pressure apa adanya dari simulator (bisa negatif ekstrem)
      - p_clean : pressure dibersihkan (negatif -> 0) untuk kebutuhan 'service impact'
      - used_time: waktu yang benar-benar dipakai (detik)
    """
    sim = wntr.sim.EpanetSimulator(wn)
    results = sim.run_sim()
    times = results.node["pressure"].index

    if time_sec not in times:
        used_time = int(times[0])
    else:
        used_time = int(time_sec)

    p_raw = results.node["pressure"].loc[used_time, :].copy()

    # untuk analisis layanan: pressure negatif dianggap 0 (mati)
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

    wntr.graphics.plot_network(
        wn,
        node_attribute=None,
        node_size=0,
        title=title,
        show_plot=False,
        ax=ax
    )

    color_map = {
        "MATI TOTAL": "red",
        "SANGAT RENDAH (0-1 bar)": "orange",
        f"RENDAH (1-{OK_BAR_MIN:g} bar)": "yellow",
        f"OK (>= {OK_BAR_MIN:g} bar)": "green",
    }

    for cat, color in color_map.items():
        sub = dfp[dfp["status"] == cat]
        if len(sub) == 0:
            continue
        ax.scatter(sub["x"], sub["y"], s=18, c=color, label=cat, zorder=5)

    ax.legend(loc="best")
    ax.set_xticks([])
    ax.set_yticks([])
    plt.tight_layout()
    plt.show()


def main():
    if not INP_PATH.exists():
        raise FileNotFoundError(f"INP tidak ditemukan: {INP_PATH}")

    # =========================
    # 1) BASE
    # =========================
    wn_base = wntr.network.WaterNetworkModel(str(INP_PATH))
    if PIPE_TO_CLOSE not in wn_base.link_name_list:
        raise ValueError(f"Pipa '{PIPE_TO_CLOSE}' tidak ditemukan di model.")

    p_base_raw_m, p_base_clean_m, used_time = run_pressure_at_time(wn_base, TIME_SEC)

    # =========================
    # 2) CLOSED
    # =========================
    wn_closed = wntr.network.WaterNetworkModel(str(INP_PATH))
    wn_closed.get_link(PIPE_TO_CLOSE).initial_status = "Closed"
    p_closed_raw_m, p_closed_clean_m, _ = run_pressure_at_time(wn_closed, used_time)

    # =========================
    # 3) ΔP (PAKAI CLEAN supaya tidak meledak -404k m)
    # =========================
    dp_m = (p_base_clean_m - p_closed_clean_m)

    # Konversi bar (pakai clean juga)
    p_base_bar = p_base_clean_m.apply(m_to_bar)
    p_closed_bar = p_closed_clean_m.apply(m_to_bar)
    dp_bar = dp_m.apply(m_to_bar)

    # =========================
    # 4) Report tabel ringkas
    # =========================
    df = pd.DataFrame({
        "P_base_m": p_base_clean_m,
        "P_closed_m": p_closed_clean_m,
        "Drop_m": dp_m,
        "P_base_bar": p_base_bar,
        "P_closed_bar": p_closed_bar,
        "Drop_bar": dp_bar
    })
    df["P_closed (m ≈ bar)"] = df["P_closed_m"].apply(fmt_m_bar)
    df["Drop (m ≈ bar)"] = df["Drop_m"].apply(fmt_m_bar)
    df["Status"] = df["P_closed_bar"].apply(service_status)

    top_impacted = df.sort_values("Drop_m", ascending=False).head(TOP_N)

    print("\n=== SERVICE IMPACT REPORT ===")
    print(f"Pipa ditutup : {PIPE_TO_CLOSE}")
    print(f"Waktu        : {used_time}s ({used_time/3600:.2f} jam)")
    print(f"Rule OK      : OK jika >= {OK_BAR_MIN:g} bar")
    print("Catatan      : Pressure negatif dari simulator di-set 0 untuk analisis layanan.\n")

    print(f"Mean P_base  : {p_base_clean_m.mean():.3f} m ≈ {p_base_bar.mean():.3f} bar")
    print(f"Mean P_closed: {p_closed_clean_m.mean():.3f} m ≈ {p_closed_bar.mean():.3f} bar")
    print(f"Mean Drop    : {dp_m.mean():.3f} m ≈ {dp_bar.mean():.3f} bar\n")

    print(f"Top {TOP_N} node terdampak (drop terbesar) — tekanan akhir & status:")
    print(top_impacted[["P_closed (m ≈ bar)", "Drop (m ≈ bar)", "Status"]])

    # =========================
    # 5) VISUALISASI 1: 3 panel
    # =========================
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    wntr.graphics.plot_network(
        wn_base,
        node_attribute=p_base_clean_m,
        node_size=20,
        title=f"Pressure BASE (t={used_time}s)",
        show_plot=False,
        ax=axes[0],
        node_colorbar_label="Pressure (m)"
    )

    wntr.graphics.plot_network(
        wn_closed,
        node_attribute=p_closed_clean_m,
        node_size=20,
        title=f"Pressure CLOSED '{PIPE_TO_CLOSE}' (t={used_time}s)",
        show_plot=False,
        ax=axes[1],
        node_colorbar_label="Pressure (m)"
    )

    wntr.graphics.plot_network(
        wn_closed,
        node_attribute=dp_m,
        node_size=20,
        title="ΔPressure = BASE - CLOSED",
        show_plot=False,
        ax=axes[2],
        node_colorbar_label="ΔPressure (m)"
    )

    plt.tight_layout()
    plt.show()

    # =========================
    # 6) VISUALISASI 2: Service Impact Map
    # =========================
    plot_service_categories(
        wn_closed,
        p_closed_bar,
        title=(
            f"Service Impact Map AFTER closing '{PIPE_TO_CLOSE}' (t={used_time}s)\n"
            f"Red=MATI, Orange=0–1 bar, Yellow=1–{OK_BAR_MIN:g} bar, Green>= {OK_BAR_MIN:g} bar"
        )
    )


if __name__ == "__main__":
    main()
