#!/usr/bin/env python3
"""Histerezisli ve tek eşikli alarmı AYNI eğim kaydı üzerinde karşılaştırır.

egim_alarmi.py her örneğin açısını olcum/egim_<zaman>.csv dosyasına yazar.
Bu program o kaydı okuyup açıları sırayla iki alarmdan da geçirir; böylece
iki yöntem elle tekrarlanamayan aynı hareketle karşılaştırılmış olur.
Alarm mantığı egim_alarmi.py'deki Alarm sınıfının kendisidir.

Kullanım:
    python histerezis_karsilastir.py ../olcum/egim_20261103_193449.csv
    python histerezis_karsilastir.py kayit1.csv kayit2.csv --ust 30 --alt 25 --pencere 10

Çıktı: ekrana tablo + olcum/histerezis_karsilastirma.csv
"""
import argparse
import csv
import statistics
from collections import deque
from pathlib import Path

from egim_alarmi import Alarm

KISA_S = 0.5    # bundan kısa süren alarm durumları "titreşim" sayılır


def kaydi_oku(yol):
    """(t_s, açı) listesi ve kayıttaki canlı alarm durumları."""
    with open(yol, newline="") as f:
        satirlar = list(csv.DictReader(f))
    t0 = int(satirlar[0]["t_ms"])
    ornekler = [((int(s["t_ms"]) - t0) / 1000.0, float(s["aci_derece"])) for s in satirlar]
    canli = [int(s["alarm"]) for s in satirlar]
    return ornekler, canli


def degisim_say(durumlar):
    onceki, sayi = 0, 0
    for d in durumlar:
        if d != onceki:
            sayi += 1
            onceki = d
    return sayi


def benzet(ornekler, ust, alt, pencere, histerezis):
    """Kaydı alarmdan geçirir: değişim sayısı, kısa durum sayısı, alarmda süre."""
    alarm = Alarm(ust, alt, histerezis=histerezis)
    son = deque(maxlen=pencere)
    degisim_anlari = []
    alarm_suresi = 0.0
    onceki_t = None
    for t, aci in ornekler:
        if onceki_t is not None and alarm.acik:
            alarm_suresi += t - onceki_t
        son.append(aci)
        if alarm.guncelle(statistics.fmean(son)):
            degisim_anlari.append(t)
        onceki_t = t
    kisa = sum(1 for a, b in zip(degisim_anlari, degisim_anlari[1:]) if b - a < KISA_S)
    return len(degisim_anlari), kisa, alarm_suresi


def main():
    ap = argparse.ArgumentParser(description="Aynı kayıtta histerezisli / tek eşik karşılaştırması")
    ap.add_argument("kayitlar", nargs="+", help="egim_alarmi.py'nin yazdığı egim_*.csv dosyaları")
    ap.add_argument("--ust", type=float, default=30.0)
    ap.add_argument("--alt", type=float, default=25.0)
    ap.add_argument("--pencere", type=int, default=10)
    ap.add_argument("--cikti", default=str(Path(__file__).resolve().parent.parent
                                           / "olcum" / "histerezis_karsilastirma.csv"))
    args = ap.parse_args()

    sonuclar = []
    for yol in args.kayitlar:
        ornekler, canli = kaydi_oku(yol)
        sure = ornekler[-1][0]
        print(f"\nKayıt: {Path(yol).name}  ({len(ornekler)} örnek, {sure:.1f} s, "
              f"açı {min(a for _, a in ornekler):+.1f}° .. {max(a for _, a in ornekler):+.1f}°)")
        print(f"  kayıt sırasındaki canlı LED değişimi: {degisim_say(canli)}")
        print(f"  {'mod':<14}{'LED değişimi':>14}{'<0,5 s durum':>14}{'alarmda':>10}")
        for histerezis, ad in ((True, "histerezisli"), (False, "tek eşik")):
            degisim, kisa, alarm_s = benzet(ornekler, args.ust, args.alt, args.pencere, histerezis)
            print(f"  {ad:<14}{degisim:>14}{kisa:>14}{alarm_s:>9.1f}s")
            sonuclar.append([Path(yol).name, ad, args.ust, args.alt if histerezis else args.ust,
                             args.pencere, len(ornekler), f"{sure:.1f}", degisim, kisa,
                             f"{alarm_s:.1f}"])

    with open(args.cikti, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["kayit", "mod", "ust", "alt", "pencere", "ornek", "sure_s",
                    "led_degisim", "kisa_durum", "alarmda_s"])
        w.writerows(sonuclar)
    print(f"\nTablo: {args.cikti}")


if __name__ == "__main__":
    main()
