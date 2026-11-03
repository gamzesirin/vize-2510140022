"""Vize raporu şekilleri: olcum/ kayıtlarından çizilir.

Kullanım: python sekil_ciz.py <olcum klasörü> <çıktı klasörü>
"""
import csv
import statistics
import sys
from collections import deque
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OLCUM, CIKTI = Path(sys.argv[1]), Path(sys.argv[2])
CIKTI.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "font.family": "Carlito", "font.size": 8.5, "axes.titlesize": 9,
    "axes.labelsize": 8.5, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": "#8a8984", "axes.linewidth": 0.6,
    "xtick.color": "#52514e", "ytick.color": "#52514e",
    "axes.labelcolor": "#2b2b2a", "text.color": "#0b0b0b",
})
MAVI, TURUNCU = "#2a78d6", "#eb6834"      # kategorik 1-2: histerezisli, tek eşik
ACI = "#52514e"                            # sinyal: nötr koyu gri
IZGARA = "#e4e3de"
ANA = "#1f4e79"                            # rapor ana rengi (blok şema)


# ---------------------------------------------------------------- alarm benzetimi
class Alarm:
    """pi/egim_alarmi.py'deki Alarm sınıfının aynısı."""

    def __init__(self, ust, alt, histerezis=True):
        self.ust, self.alt, self.histerezis = ust, alt, histerezis
        self.acik = False

    def guncelle(self, aci):
        a = abs(aci)
        yeni = (a > self.ust if not self.acik else a >= self.alt) if self.histerezis else a > self.ust
        degisti = yeni != self.acik
        self.acik = yeni
        return degisti


def kayit(ad):
    with open(OLCUM / ad, newline="") as f:
        s = list(csv.DictReader(f))
    t0 = int(s[0]["t_ms"])
    return [(int(r["t_ms"]) - t0) / 1000 for r in s], [float(r["aci_derece"]) for r in s]


def benzet(acilar, histerezis):
    alarm, son, ort, durum, sayi = Alarm(30, 25, histerezis), deque(maxlen=10), [], [], 0
    for a in acilar:
        son.append(a)
        o = statistics.fmean(son)
        sayi += alarm.guncelle(o)
        ort.append(o)
        durum.append(int(alarm.acik))
    return ort, durum, sayi


def panel(fig, gs, t, acilar, baslik, xlim=None, harf="", etiket=(0.3, "ust")):
    ort, d_h, n_h = benzet(acilar, True)
    _, d_t, n_t = benzet(acilar, False)
    sub = gs.subgridspec(3, 1, height_ratios=[3.2, 0.55, 0.55], hspace=0.12)
    ax = fig.add_subplot(sub[0])
    ax.plot(t, ort, color=ACI, lw=1.1)
    ax.axhline(30, color="#0b0b0b", lw=0.8, ls=(0, (4, 2)))
    ax.axhline(25, color="#0b0b0b", lw=0.8, ls=(0, (1, 2)))
    if not xlim:
        x0, yer = t[0] + etiket[0], etiket[1]
        dy, va = (0.4, "bottom") if yer == "ust" else (-0.4, "top")
        ax.text(x0, 30 + dy, "üst eşik 30°", ha="left", va=va, fontsize=7.2, color="#2b2b2a")
        ax.text(x0, 25 + dy, "alt eşik 25°", ha="left", va=va, fontsize=7.2, color="#2b2b2a")
    ax.set_ylabel("eğim (°)")
    ax.set_title(f"{harf} {baslik}", loc="left", fontweight="bold")
    ax.grid(axis="y", color=IZGARA, lw=0.5)
    ax.tick_params(labelbottom=False)
    for i, (d, n, renk, ad) in enumerate(((d_h, n_h, MAVI, "histerezisli"),
                                          (d_t, n_t, TURUNCU, "tek eşik"))):
        a2 = fig.add_subplot(sub[i + 1], sharex=ax)
        a2.fill_between(t, d, step="post", color=renk, lw=0, alpha=0.9)
        a2.set_ylim(0, 1.05)
        a2.set_yticks([])
        a2.spines["left"].set_visible(False)
        a2.text(-0.01, 0.5, f"{ad}\n{n} değişim", transform=a2.transAxes, ha="right",
                va="center", fontsize=7.2, color="#2b2b2a", linespacing=0.95)
        if i == 0:
            a2.tick_params(labelbottom=False)
        else:
            a2.set_xlabel("süre (s)")
    if xlim:
        ax.set_xlim(*xlim)
    return ax


# ---------------------------------------------------------------- Şekil 2: histerezis
t_e, a_e = kayit("egim_20261103_193449.csv")     # eşikte bekleme (canlı: tek eşik)
t_s, a_s = kayit("egim_20261103_192848.csv")     # geniş salınım (canlı: histerezisli)

fig = plt.figure(figsize=(7.1, 4.45))
gs = fig.add_gridspec(2, 2, width_ratios=[2.15, 1], height_ratios=[1, 1],
                      hspace=0.55, wspace=0.42, left=0.115, right=0.985, top=0.95, bottom=0.09)
ax_a = panel(fig, gs[0, 0], t_e, a_e, "Eşikte bekleme (27–38°)", harf="(a)", etiket=(15, "alt"))
ax_a.set_ylim(22.5, 38.5)
ax_a.axvspan(5.8, 8.8, color="#d9d8d2", alpha=0.55, lw=0)
ax_b = panel(fig, gs[0, 1], t_e, a_e, "(a)'nın 5,8–8,8 s aralığı", xlim=(5.8, 8.8), harf="(b)")
ax_b.set_ylim(28.8, 31.2)
ax_c = panel(fig, gs[1, :], t_s, a_s, "Geniş salınım (18–51°)", harf="(c)")
fig.savefig(CIKTI / "sekil2_histerezis.png", dpi=220)
plt.close(fig)


# ---------------------------------------------------------------- Şekil 1: blok şema
def kutu(ax, x, y, w, h, baslik, satirlar, renk=ANA, dolgu="#e9f0f7"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.006,rounding_size=0.012",
                                fc=dolgu, ec=renk, lw=1.0))
    ax.text(x + w / 2, y + h - 0.035, baslik, ha="center", va="top", fontsize=8.6,
            fontweight="bold", color=renk)
    ax.text(x + 0.012, y + h - 0.105, "\n".join(satirlar), ha="left", va="top", fontsize=7.1,
            color="#1a1a1a", linespacing=1.28)


def ok(ax, x0, y0, x1, y1, yazi, yer="ust", renk="#2b2b2a"):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=8,
                                 lw=0.9, color=renk, shrinkA=0, shrinkB=0))
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    ax.text(xm, ym + (0.018 if yer == "ust" else -0.018), yazi, ha="center",
            va="bottom" if yer == "ust" else "top", fontsize=6.9, color="#2b2b2a")


fig = plt.figure(figsize=(7.1, 1.95))
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")
kutu(ax, 0.005, 0.36, 0.15, 0.46, "MPU-6050", ["GY-521 (MPU-6500)", "ivme ±2 g", "dönü ±250 °/s",
                                                "I²C adresi 0x68"])
kutu(ax, 0.25, 0.03, 0.285, 0.94, "ESP32-S3", [
    "olcum_gorevi  (öncelik 5)",
    "  xTaskDelayUntil, 50 Hz (HIZ: 1–100)",
    "  14 bayt oku → \\$IMU satırı",
    "  yerel_uyari: |θ| > ESIK → GPIO5",
    "alma_gorevi  (öncelik 6)",
    "  bayt bayt oku, '$' ile senkron",
    "  checksum → LED (GPIO4) / HIZ / ESIK",
    "  → \\$ACK veya \\$ERR",
    "UART yazımı mutex ile korunur"])
kutu(ax, 0.68, 0.03, 0.315, 0.94, "Raspberry Pi 4", [
    "protokol.py: kodla / coz / imu_coz",
    "alici.py: doğrula, CSV, komut, ACK süresi",
    "egim_alarmi.py (V1):",
    "  θ = atan2(ax, az), 10 örnek ortalama",
    "  histerezis 30° / 25°",
    "  durum değişince \\$LED, başta \\$ESIK",
    "  olay günlüğü (alarm_olaylari.csv)",
    "histerezis_karsilastir.py:",
    "  aynı kaydı iki moddan geçirir"])
ok(ax, 0.155, 0.61, 0.25, 0.61, "I²C 400 kHz", "ust")
ax.text(0.2025, 0.56, "SDA 8 · SCL 9", ha="center", va="top", fontsize=6.6, color="#52514e")
ok(ax, 0.535, 0.68, 0.68, 0.68, "\\$IMU · \\$ACK · \\$ERR", "ust")
ok(ax, 0.68, 0.52, 0.535, 0.52, "\\$LED · \\$HIZ · \\$ESIK", "alt")
ax.text(0.6075, 0.40, "UART1 115200 8N1\nTX17→RXD (pin 10)\nRX18←TXD (pin 8)\nortak GND",
        ha="center", va="top", fontsize=6.6, color="#52514e", linespacing=1.2)
fig.savefig(CIKTI / "sekil1_mimari.png", dpi=220)
plt.close(fig)
print("şekiller:", sorted(p.name for p in CIKTI.iterdir()))
