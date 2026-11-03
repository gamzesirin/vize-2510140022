#!/usr/bin/env python3
"""ESP32 benzetici: donanım olmadan Pi tarafını denemek için sanal seri port.

Bir sanal seri port (pty) açar, ESP32 gibi $IMU satırları gönderir ve gelen
komutlara $ACK / $ERR ile yanıt verir. Sanal sensör y ekseni etrafında
12 s periyotla ±50° sallanır.

Kullanım:
    python sim_esp32.py                   # ekrana sanal port adını yazar
    python alici.py --port /dev/pts/N     # ikinci terminalde
    python sim_esp32.py --hata-orani 0.01 # satırların %1'inin checksum'ını boz
"""
import argparse
import math
import os
import random
import select
import time
import tty

from protokol import ProtokolHatasi, checksum, coz, kodla


class SanalESP32:
    def __init__(self, hata_orani):
        self.hz = 50
        self.led = 0
        self.hata_orani = hata_orani
        self.baslangic = time.monotonic()

    def imu_govdesi(self):
        t = time.monotonic() - self.baslangic
        aci = math.radians(50 * math.sin(2 * math.pi * t / 12) + random.gauss(0, 0.5))
        aci_hizi = 50 * 2 * math.pi / 12 * math.cos(2 * math.pi * t / 12)       # °/s
        ax = int(16384 * math.sin(aci) + random.gauss(0, 80))
        ay = int(random.gauss(0, 80))
        az = int(16384 * math.cos(aci) + random.gauss(0, 80))
        gx, gy, gz = (int(random.gauss(0, 30)), int(131 * aci_hizi), int(random.gauss(0, 30)))
        return f"IMU,{int(t * 1000)},{ax},{ay},{az},{gx},{gy},{gz}"

    def komut(self, satir):
        """Gelen bir satıra verilecek yanıt gövdesi."""
        try:
            alanlar = coz(satir)
        except ProtokolHatasi as h:
            return f"ERR,{h.neden}"
        komut, deger = alanlar[0], alanlar[1] if len(alanlar) > 1 else ""
        if komut not in ("LED", "HIZ"):
            return "ERR,KOMUT"
        if not deger.isdigit():
            return "ERR,BICIM"
        sayi = int(deger)
        if komut == "LED" and sayi in (0, 1):
            self.led = sayi
            print(f"LED {'yandı' if sayi else 'söndü'}")
        elif komut == "HIZ" and 1 <= sayi <= 100:
            self.hz = sayi
            print(f"Ölçüm hızı {sayi} Hz")
        else:
            return "ERR,BICIM"
        return f"ACK,{komut},{sayi}"


def satir(govde, boz=False):
    if boz:  # yanlış checksum
        return f"${govde}*{checksum(govde) ^ 0x5A:02X}\r\n".encode("ascii")
    return kodla(govde)


def main():
    ap = argparse.ArgumentParser(description="ESP32 benzetici")
    ap.add_argument("--hata-orani", type=float, default=0.0, help="checksum'ı bozulacak satır oranı")
    args = ap.parse_args()

    ana, yan = os.openpty()
    tty.setraw(yan)                 # yankı ve satır düzenleme kapalı, gerçek UART gibi
    os.set_blocking(ana, False)
    print(f"Sanal port: {os.ttyname(yan)}")
    print(f"İkinci terminalde: python alici.py --port {os.ttyname(yan)}")

    esp = SanalESP32(args.hata_orani)
    tampon = b""
    sonraki = time.monotonic()
    try:
        while True:
            bekle = max(0.0, sonraki - time.monotonic())
            hazir, _, _ = select.select([ana], [], [], bekle)
            if hazir:
                try:
                    tampon += os.read(ana, 1024)
                except BlockingIOError:
                    pass
                while b"\n" in tampon:
                    gelen, tampon = tampon.split(b"\n", 1)
                    if b"$" in gelen:       # ESP32 gibi: son '$' öncesindeki yarım veri atılır
                        gelen = gelen[gelen.rfind(b"$"):]
                    if gelen.strip():
                        yanit = esp.komut(gelen)
                        os.write(ana, satir(yanit))
            if time.monotonic() >= sonraki:
                try:
                    os.write(ana, satir(esp.imu_govdesi(), random.random() < esp.hata_orani))
                except BlockingIOError:
                    pass            # okuyan yoksa satır kaybolur, gerçek UART'taki gibi
                sonraki += 1.0 / esp.hz
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
