"""ESP32 ile Raspberry Pi arasındaki satır protokolü.

Her satır  $GOVDE*HH\\r\\n  biçimindedir. GOVDE'deki alanlar virgülle ayrılır.
HH, $ ile * arasındaki karakterlerin ASCII kodlarının XOR'udur (iki haneli onaltılık).

    ESP32 -> Pi : $IMU,t,ax,ay,az,gx,gy,gz   $ACK,<komut>,<değer>   $ERR,<neden>
    Pi -> ESP32 : $LED,0|1                   $HIZ,1..100
                  $ESIK,1..89  (V1 eklemesi: ESP32'nin kendi eğim uyarısı için eşik, derece)
"""

IVME_LSB_G = 16384.0     # ±2 g aralığında 1 g
DONU_LSB_DPS = 131.0     # ±250 °/s aralığında 1 °/s


class ProtokolHatasi(ValueError):
    """Satır protokole uymuyor. neden: 'BICIM' veya 'CHECKSUM'."""

    def __init__(self, neden, satir):
        super().__init__(f"{neden}: {satir!r}")
        self.neden = neden
        self.satir = satir


def checksum(govde):
    """$ ile * arasındaki metnin XOR'u."""
    sonuc = 0
    for bayt in govde.encode("ascii"):
        sonuc ^= bayt
    return sonuc


def kodla(govde):
    """'LED,1' -> b'$LED,1*50\\r\\n'"""
    return f"${govde}*{checksum(govde):02X}\r\n".encode("ascii")


def coz(satir):
    """Satırı doğrular ve alanlarını liste olarak döndürür: ['IMU', '1234', ...].

    Satır bytes ya da str olabilir. Protokole uymuyorsa ProtokolHatasi fırlatır.
    """
    if isinstance(satir, bytes):
        try:
            satir = satir.decode("ascii")
        except UnicodeDecodeError:
            raise ProtokolHatasi("BICIM", satir)
    satir = satir.strip()
    if not satir.startswith("$") or "*" not in satir:
        raise ProtokolHatasi("BICIM", satir)
    govde, _, hh = satir[1:].rpartition("*")
    if len(hh) != 2:
        raise ProtokolHatasi("BICIM", satir)
    try:
        gelen = int(hh, 16)
    except ValueError:
        raise ProtokolHatasi("BICIM", satir)
    if gelen != checksum(govde):
        raise ProtokolHatasi("CHECKSUM", satir)
    return govde.split(",")


def imu_coz(alanlar):
    """IMU alanlarını birimlerine çevirir: t_ms, ax/ay/az (g), gx/gy/gz (°/s)."""
    if len(alanlar) != 8 or alanlar[0] != "IMU":
        raise ProtokolHatasi("BICIM", ",".join(alanlar))
    try:
        t, ax, ay, az, gx, gy, gz = (int(a) for a in alanlar[1:])
    except ValueError:
        raise ProtokolHatasi("BICIM", ",".join(alanlar))
    return {
        "t_ms": t,
        "ax": ax / IVME_LSB_G, "ay": ay / IVME_LSB_G, "az": az / IVME_LSB_G,
        "gx": gx / DONU_LSB_DPS, "gy": gy / DONU_LSB_DPS, "gz": gz / DONU_LSB_DPS,
    }


if __name__ == "__main__":
    # Yönergedeki örnek: LED,1 -> $LED,1*50
    assert kodla("LED,1") == b"$LED,1*50\r\n"
    print(kodla("LED,1"), kodla("HIZ,25"))
