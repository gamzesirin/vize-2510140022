#!/usr/bin/env python3
"""V1 eklemesi: eğim alarmı.

Her $IMU satırından eğim açısını θ = atan2(ax, az) ile hesaplar, son N örneğin
ortalamasıyla süzer ve histerezisli eşik uygular:
    |θ| üst eşiği geçince   -> $LED,1   (alarm başladı)
    |θ| alt eşiğin altına inince -> $LED,0   (alarm bitti)
Komut yalnızca alarm durumu değiştiğinde gönderilir. Başlangıçta üst eşik
$ESIK komutuyla ESP32'ye de bildirilir; ESP32 GPIO5'teki LED ile kendi uyarısını verir.

Kullanım:
    python egim_alarmi.py                         # üst 30°, alt 25°, pencere 10
    python egim_alarmi.py --ust 40 --alt 35
    python egim_alarmi.py --histerezis-yok        # karşılaştırma için tek eşik
    python egim_alarmi.py --olc 10 --gercek 45    # 10 s açı ölçüp doğruluk tablosuna ekle
    python egim_alarmi.py --port /dev/pts/3       # sim_esp32.py ile

Klavyeden:  esik <üst> <alt>  (ör. esik 40 35)  |  q
Kayıtlar (olcum/):
    egim_<zaman>.csv        her örnek: zaman, t_ms, θ, ortalama θ, alarm
    alarm_olaylari.csv      alarm başlama/bitme olayları (ekleyerek yazılır)
    aci_dogrulugu.csv       --olc ölçümleri (ekleyerek yazılır)
"""
import argparse
import csv
import math
import queue
import statistics
import sys
import threading
import time
from collections import Counter, deque
from datetime import datetime
from pathlib import Path

import serial

from protokol import ProtokolHatasi, coz, imu_coz, kodla

KLASOR = Path(__file__).resolve().parent.parent / "olcum"


def egim(o):
    """İvmeden eğim açısı (derece): sensör düzken 0°, x ekseni dikken ±90°."""
    return math.degrees(math.atan2(o["ax"], o["az"]))


class Alarm:
    """Histerezisli (ya da tek eşikli) alarm durumu."""

    def __init__(self, ust, alt, histerezis=True):
        self.ust, self.alt, self.histerezis = ust, alt, histerezis
        self.acik = False

    def guncelle(self, aci):
        """Durum değiştiyse True döndürür."""
        a = abs(aci)
        if self.histerezis:
            yeni = a > self.ust if not self.acik else a >= self.alt
        else:
            yeni = a > self.ust
        degisti = yeni != self.acik
        self.acik = yeni
        return degisti


def klavye_dinle(kuyruk):
    for satir in sys.stdin:
        kuyruk.put(satir.strip())


def ekleyerek_yaz(yol, baslik, satir):
    yeni = not yol.exists()
    with open(yol, "a", newline="") as f:
        w = csv.writer(f)
        if yeni:
            w.writerow(baslik)
        w.writerow(satir)


def main():
    ap = argparse.ArgumentParser(description="V1 eğim alarmı")
    ap.add_argument("--port", default="/dev/serial0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--ust", type=float, default=30.0, help="alarmın başladığı eğim (derece)")
    ap.add_argument("--alt", type=float, default=25.0, help="alarmın bittiği eğim (derece)")
    ap.add_argument("--pencere", type=int, default=10, help="ortalaması alınan örnek sayısı")
    ap.add_argument("--histerezis-yok", action="store_true", help="tek eşik (yalnızca --ust)")
    ap.add_argument("--sure", type=float, default=0, help="saniye; 0 = q yazılana kadar")
    ap.add_argument("--olc", type=float, default=0, metavar="S",
                    help="S saniye açı ölçüp istatistiği yaz (alarm çalışmaz)")
    ap.add_argument("--gercek", type=float, help="--olc için sensörün gerçek açısı (derece)")
    args = ap.parse_args()
    if args.alt > args.ust:
        ap.error("--alt, --ust'ten büyük olamaz")

    KLASOR.mkdir(exist_ok=True)
    port = serial.Serial(args.port, args.baud, timeout=0.05)
    kuyruk = queue.Queue()
    threading.Thread(target=klavye_dinle, args=(kuyruk,), daemon=True).start()

    alarm = Alarm(args.ust, args.alt, histerezis=not args.histerezis_yok)
    pencere = deque(maxlen=args.pencere)
    hatalar = Counter()
    bekleyen = {}
    degisim = 0
    alarm_suresi = 0.0
    alarm_basi = None
    olc_acilari = []

    def gonder(govde):
        port.write(kodla(govde))
        bekleyen[govde.split(",")[0]] = time.perf_counter()

    olay_yolu = KLASOR / "alarm_olaylari.csv"
    kayit_yolu = KLASOR / time.strftime("egim_%Y%m%d_%H%M%S.csv")
    mod = "tek eşik" if args.histerezis_yok else "histerezisli"
    if args.olc:
        print(f"Açı ölçümü: {args.olc:.0f} s, gerçek açı {args.gercek}°")
    else:
        print(f"Eğim alarmı ({mod}): üst {args.ust:g}°, alt {args.alt:g}°, pencere {args.pencere}")
        print("Komutlar: esik <üst> <alt>, q")
        gonder(f"ESIK,{round(args.ust)}")

    baslangic = time.monotonic()
    son_ekran = baslangic
    with open(kayit_yolu, "w", newline="") as kayit:
        yazici = csv.writer(kayit)
        yazici.writerow(["pi_zaman_s", "t_ms", "aci_derece", "ort_aci_derece", "alarm"])
        try:
            while True:
                simdi = time.monotonic()
                sure = args.olc or args.sure
                if sure and simdi - baslangic >= sure:
                    break

                try:
                    metin = kuyruk.get_nowait()
                except queue.Empty:
                    metin = None
                if metin:
                    p = metin.split()
                    if p[0].lower() == "q":
                        break
                    if p[0].lower() == "esik" and len(p) == 3:
                        try:
                            ust, alt = float(p[1]), float(p[2])
                        except ValueError:
                            ust = alt = None
                        if ust is not None and 1 <= alt <= ust <= 89:
                            alarm.ust, alarm.alt = ust, alt
                            gonder(f"ESIK,{round(ust)}")
                            print(f"Eşik: üst {ust:g}°, alt {alt:g}°")
                            continue
                    print("Örnek: esik 40 35  |  q")

                ham = port.readline()
                if not ham:
                    continue
                try:
                    alanlar = coz(ham)
                    if alanlar[0] == "IMU":
                        o = imu_coz(alanlar)
                except ProtokolHatasi as h:
                    hatalar[h.neden] += 1
                    continue

                if alanlar[0] == "ACK":
                    t0 = bekleyen.pop(alanlar[1], None)
                    ek = f" ({(time.perf_counter() - t0) * 1000:.1f} ms)" if t0 else ""
                    print(f"<- ACK {','.join(alanlar[1:])}{ek}")
                    continue
                if alanlar[0] == "ERR":
                    print(f"<- ESP32 hata: {','.join(alanlar[1:])}")
                    continue
                if alanlar[0] != "IMU":
                    continue

                aci = egim(o)
                pencere.append(aci)
                ort = statistics.fmean(pencere)

                if args.olc:
                    olc_acilari.append(aci)
                elif alarm.guncelle(ort):
                    degisim += 1
                    gonder(f"LED,{int(alarm.acik)}")
                    olay = "ALARM_BASLADI" if alarm.acik else "ALARM_BITTI"
                    if alarm.acik:
                        alarm_basi = simdi
                    elif alarm_basi is not None:
                        alarm_suresi += simdi - alarm_basi
                        alarm_basi = None
                    ekleyerek_yaz(olay_yolu,
                                  ["zaman", "t_ms", "ort_aci_derece", "olay", "mod", "ust", "alt"],
                                  [datetime.now().isoformat(timespec="milliseconds"), o["t_ms"],
                                   f"{ort:.2f}", olay, mod, args.ust, alarm.alt])
                    print(f"** {olay}  (ortalama eğim {ort:+.1f}°) -> $LED,{int(alarm.acik)}")

                yazici.writerow([f"{time.time():.3f}", o["t_ms"], f"{aci:.2f}", f"{ort:.2f}",
                                 int(alarm.acik)])
                if simdi - son_ekran >= 1.0:
                    durum = "AÇIK" if alarm.acik else "kapalı"
                    print(f"[{simdi - baslangic:5.0f} s] eğim {aci:+6.1f}°  ortalama {ort:+6.1f}°  "
                          f"alarm {durum}")
                    son_ekran = simdi
        except KeyboardInterrupt:
            pass

    sure = time.monotonic() - baslangic
    if alarm_basi is not None:
        alarm_suresi += time.monotonic() - alarm_basi
    port.close()

    print("\n--- Özet ---")
    if args.olc and olc_acilari:
        ort = statistics.fmean(olc_acilari)
        ss = statistics.pstdev(olc_acilari)
        print(f"{len(olc_acilari)} örnek: ortalama {ort:+.2f}°, standart sapma {ss:.2f}°, "
              f"en küçük {min(olc_acilari):+.2f}°, en büyük {max(olc_acilari):+.2f}°")
        if args.gercek is not None:
            print(f"Gerçek açı {args.gercek:g}°, hata {abs(ort) - args.gercek:+.2f}°")
            ekleyerek_yaz(KLASOR / "aci_dogrulugu.csv",
                          ["gercek_derece", "ort_derece", "ss_derece", "min", "max", "n"],
                          [args.gercek, f"{ort:.2f}", f"{ss:.2f}", f"{min(olc_acilari):.2f}",
                           f"{max(olc_acilari):.2f}", len(olc_acilari)])
    else:
        print(f"Süre {sure:.1f} s, mod: {mod}, LED değişim sayısı: {degisim}, "
              f"alarmda geçen süre: {alarm_suresi:.1f} s")
    print(f"Hatalı satır: {sum(hatalar.values())} {dict(hatalar) if hatalar else ''}")
    print(f"Kayıt: {kayit_yolu}")


if __name__ == "__main__":
    main()
