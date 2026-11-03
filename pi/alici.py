#!/usr/bin/env python3
"""ESP32'den gelen ölçüm satırlarını okur, doğrular, CSV'ye yazar ve komut gönderir.

Kullanım:
    python alici.py                          # /dev/serial0, 115200
    python alici.py --port /dev/pts/3        # sim_esp32.py ile, donanımsız
    python alici.py --sure 60                # 60 s sonra özet verip çık
    python alici.py --ack-testi 20           # 20 LED komutunun ACK süresini ölç

Klavyeden (yazıp Enter):  led 0 | led 1 | hiz 1..100 | q
"""
import argparse
import csv
import queue
import statistics
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import serial

from protokol import ProtokolHatasi, coz, imu_coz, kodla

KOMUTLAR = {"led": "LED", "hiz": "HIZ"}


def klavye_dinle(kuyruk):
    """stdin'den gelen satırları ana döngüye iletir."""
    for satir in sys.stdin:
        kuyruk.put(satir.strip())


def komut_cevir(metin):
    """'led 1' -> 'LED,1'; tanınmıyorsa None."""
    parcalar = metin.split()
    if len(parcalar) == 2 and parcalar[0].lower() in KOMUTLAR and parcalar[1].isdigit():
        return f"{KOMUTLAR[parcalar[0].lower()]},{parcalar[1]}"
    return None


def main():
    ap = argparse.ArgumentParser(description="ESP32 ölçüm alıcısı")
    ap.add_argument("--port", default="/dev/serial0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--csv", help="çıktı dosyası (varsayılan: olcum/imu_<zaman>.csv)")
    ap.add_argument("--yazdir", type=int, default=25, help="her N geçerli satırda bir ekrana yaz")
    ap.add_argument("--sure", type=float, default=0, help="saniye; 0 = q yazılana kadar")
    ap.add_argument("--ack-testi", type=int, default=0, metavar="N",
                    help="N adet LED komutu gönderip komut-ACK süresini ölç")
    args = ap.parse_args()

    klasor = Path(__file__).resolve().parent.parent / "olcum"
    klasor.mkdir(exist_ok=True)
    csv_yolu = Path(args.csv) if args.csv else klasor / time.strftime("imu_%Y%m%d_%H%M%S.csv")

    port = serial.Serial(args.port, args.baud, timeout=0.05)
    kuyruk = queue.Queue()
    threading.Thread(target=klavye_dinle, args=(kuyruk,), daemon=True).start()

    gecerli = 0
    hatalar = Counter()          # bizim yakaladığımız hatalı satırlar: BICIM / CHECKSUM
    esp_hatalari = Counter()     # ESP32'nin gönderdiği $ERR satırları
    bekleyen = {}                # komut adı -> gönderme zamanı
    ack_sureleri = []            # ms
    ack_sirasi = 0
    kayip_ack = 0
    sonraki_ack = time.monotonic() + 2.0

    baslangic = time.monotonic()
    son_rapor, son_rapor_gecerli = baslangic, 0

    print(f"Port {args.port} @ {args.baud}, kayıt: {csv_yolu}")
    print("Komutlar: led 0|1, hiz 1..100, q")

    with open(csv_yolu, "w", newline="") as dosya:
        yazici = csv.writer(dosya)
        yazici.writerow(["pi_zaman_s", "t_ms", "ax_g", "ay_g", "az_g", "gx_dps", "gy_dps", "gz_dps"])

        def gonder(govde):
            port.write(kodla(govde))
            bekleyen[govde.split(",")[0]] = time.perf_counter()
            print(f"-> ${govde}")

        try:
            while True:
                simdi = time.monotonic()
                if args.sure and simdi - baslangic >= args.sure:
                    break

                # klavye komutları
                try:
                    metin = kuyruk.get_nowait()
                except queue.Empty:
                    metin = None
                if metin is not None:
                    if metin.lower() == "q":
                        break
                    govde = komut_cevir(metin)
                    if govde:
                        gonder(govde)
                    elif metin:
                        print("Bilinmeyen komut. Örnek: led 1, hiz 20, q")

                # yanıtı 1 s içinde gelmeyen komut kayıp sayılır
                for ad, t0 in list(bekleyen.items()):
                    if time.perf_counter() - t0 > 1.0:
                        del bekleyen[ad]
                        kayip_ack += 1
                        print(f"!! {ad} komutuna 1 s içinde yanıt gelmedi")

                # otomatik ACK testi
                if ack_sirasi < args.ack_testi and simdi >= sonraki_ack and not bekleyen:
                    gonder(f"LED,{(ack_sirasi + 1) % 2}")
                    ack_sirasi += 1
                    sonraki_ack = simdi + 0.3

                # seri porttan bir satır
                ham = port.readline()
                if ham:
                    try:
                        alanlar = coz(ham)
                    except ProtokolHatasi as h:
                        hatalar[h.neden] += 1
                        alanlar = None
                    if alanlar:
                        tip = alanlar[0]
                        if tip == "IMU":
                            try:
                                o = imu_coz(alanlar)
                            except ProtokolHatasi as h:
                                hatalar[h.neden] += 1
                            else:
                                gecerli += 1
                                yazici.writerow([f"{time.time():.3f}", o["t_ms"],
                                                 f"{o['ax']:.5f}", f"{o['ay']:.5f}", f"{o['az']:.5f}",
                                                 f"{o['gx']:.3f}", f"{o['gy']:.3f}", f"{o['gz']:.3f}"])
                                if args.yazdir and gecerli % args.yazdir == 0:
                                    print(f"t={o['t_ms']:>8} ms  ax={o['ax']:+.3f} ay={o['ay']:+.3f} "
                                          f"az={o['az']:+.3f} g  gx={o['gx']:+7.2f} gy={o['gy']:+7.2f} "
                                          f"gz={o['gz']:+7.2f} °/s")
                        elif tip == "ACK" and len(alanlar) >= 3:
                            t0 = bekleyen.pop(alanlar[1], None)
                            if t0 is not None:
                                ms = (time.perf_counter() - t0) * 1000
                                ack_sureleri.append(ms)
                                print(f"<- ACK {alanlar[1]} {alanlar[2]}  ({ms:.1f} ms)")
                            else:
                                print(f"<- ACK {','.join(alanlar[1:])}")
                        elif tip == "ERR":
                            neden = alanlar[1] if len(alanlar) > 1 else "?"
                            esp_hatalari[neden] += 1
                            bekleyen.clear()
                            print(f"<- ESP32 hata: {neden}")
                        else:
                            hatalar["BICIM"] += 1

                # 5 saniyede bir durum
                if simdi - son_rapor >= 5:
                    hiz = (gecerli - son_rapor_gecerli) / (simdi - son_rapor)
                    print(f"[{simdi - baslangic:5.0f} s] örnek hızı {hiz:5.1f} Hz | geçerli {gecerli} "
                          f"| hatalı {sum(hatalar.values())}")
                    son_rapor, son_rapor_gecerli = simdi, gecerli
                    dosya.flush()
        except KeyboardInterrupt:
            pass

    sure = time.monotonic() - baslangic
    port.close()
    print("\n--- Özet ---")
    print(f"Süre: {sure:.1f} s, geçerli satır: {gecerli}, ortalama örnek hızı: {gecerli / sure:.2f} Hz")
    print(f"Hatalı satır: {sum(hatalar.values())} {dict(hatalar) if hatalar else ''}")
    if esp_hatalari:
        print(f"ESP32'nin bildirdiği hatalar: {dict(esp_hatalari)}")
    if ack_sureleri:
        print(f"Komut-ACK süresi ({len(ack_sureleri)} komut): en kısa {min(ack_sureleri):.1f} ms, "
              f"ortalama {statistics.mean(ack_sureleri):.1f} ms, en uzun {max(ack_sureleri):.1f} ms")
    if kayip_ack:
        print(f"Yanıtsız kalan komut: {kayip_ack}")
    print(f"Kayıt: {csv_yolu}")


if __name__ == "__main__":
    main()
