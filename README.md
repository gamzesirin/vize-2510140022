# Vize Projesi – ESP32-S3 ile Raspberry Pi Haberleşmesi

ESP32-S3, MPU-6050 sensörünü 50 Hz'de okuyup ölçümleri UART üzerinden Raspberry Pi 4'e gönderir; Pi satırları checksum ile doğrular, CSV'ye kaydeder ve ESP32'ye komut gönderir. **Seçilen ekleme:** V1 – Eğim alarmı: Pi eğim açısını hesaplayıp eşik aşılınca ESP32'deki LED'i yakar; eşik `$ESIK` komutuyla ESP32'ye de gönderilir ve ESP32 ikinci bir LED ile kendi uyarısını verir.

- **Hazırlayan:** Gamze Şirin – 2510140022
- **Ders:** İleri Gömülü Sistemler (Dr. Murat Sürücü)

## Malzeme listesi

| Malzeme | Adet |
|---|---|
| ESP32-S3-N16R8 geliştirme kartı (DevKitC-1 düzeni) ve USB kablo | 1 |
| Raspberry Pi 4 Model B, 5,1 V / 3 A güç kaynağı, microSD (Raspberry Pi OS Lite 64-bit) | 1 |
| GY-521 sensör modülü (MPU-6050 uyumlu) | 1 |
| LED ve 330 Ω direnç | 2 |
| Breadboard, dişi-erkek ve erkek-erkek atlama kabloları | ~12 |

## Bağlantılar

| ESP32-S3 | Bağlandığı yer | Not |
|---|---|---|
| GPIO17 (UART1 TX) | Pi pin 10 (GPIO15, RXD) | çapraz |
| GPIO18 (UART1 RX) | Pi pin 8 (GPIO14, TXD) | çapraz |
| GND | Pi pin 6 (GND) | ortak toprak |
| 3V3 | MPU-6050 VCC | sensör 3,3 V'tan beslenir |
| GND | MPU-6050 GND | |
| GPIO8 / GPIO9 | MPU-6050 SDA / SCL | I²C, 400 kHz |
| GPIO4 | 330 Ω → LED → GND | `$LED` komutuyla sürülür (Pi'nin alarmı) |
| GPIO5 | 330 Ω → LED → GND | V1: ESP32'nin kendi eğim uyarısı |

Pi'nin 5V pinleri (2 ve 4) kullanılmaz. Kartlar ayrı USB kablolarından beslenir.

## ESP32: derleme ve yükleme

ESP-IDF v6.1 ortamında:

```
cd esp32
idf.py set-target esp32s3
idf.py build
idf.py -p /dev/cu.usbmodemXXXX flash monitor     # 'MPU-6050 bulundu' satırını görün
```

## Raspberry Pi: kurulum ve çalıştırma

Seri portu bir kez açın: `sudo raspi-config` → Interface Options → Serial Port → login shell **No**, hardware **Yes**, ardından yeniden başlatın.

```
git clone https://github.com/gamzesirin/vize-2510140022.git
cd vize-2510140022/pi
python3 -m venv ~/yz && source ~/yz/bin/activate
pip install pyserial
python alici.py                                   # /dev/serial0, 115200
python -m serial.tools.miniterm /dev/serial0 115200   # satırları ham izleme
```

`alici.py` klavye komutları: `led 0`, `led 1`, `hiz 1..100`, `esik 1..89` (V1: ESP32'nin GPIO5 uyarı eşiği), `q`. Seçenekler: `--sure 60` (60 s sonra özet), `--yazdir N` (her N satırda bir ekrana yaz), `--ack-testi 20` (20 komutun ACK süresini ölçer).

Donanım olmadan: `python sim_esp32.py` sanal bir port açar, ardından ikinci terminalde `python alici.py --port /dev/pts/N`.

### V1: eğim alarmı

```
python egim_alarmi.py                          # üst eşik 30°, alt eşik 25°, son 10 örneğin ortalaması
python egim_alarmi.py --ust 40 --alt 35        # farklı eşikler
python egim_alarmi.py --histerezis-yok         # karşılaştırma: tek eşik
python egim_alarmi.py --olc 10 --gercek 45     # 10 s açı ölçümü, olcum/aci_dogrulugu.csv'ye eklenir
python histerezis_karsilastir.py ../olcum/egim_<zaman>.csv   # aynı kaydı iki alarm modundan geçirir
```

Eğim `θ = atan2(ax, az)` ile hesaplanır (sensör düzken 0°). Son 10 örneğin ortalaması `|θ|` üst eşiği geçince `$LED,1`, alt eşiğin altına inince `$LED,0` gönderilir; komut yalnızca durum değiştiğinde gider. Program başlarken üst eşiği `$ESIK` ile ESP32'ye bildirir. Çalışırken `esik 40 35` yazarak eşikler değiştirilebilir. Alarm olayları zaman damgasıyla `olcum/alarm_olaylari.csv` dosyasına, her örneğin açısı `olcum/egim_<zaman>.csv` dosyasına yazılır.

## Protokol

Her satır `$GOVDE*HH\r\n` biçimindedir; `HH`, `$` ile `*` arasındaki karakterlerin ASCII kodlarının XOR'udur. Örnek: `$LED,1*50`.

| Yön | Mesaj | Anlamı |
|---|---|---|
| ESP32 → Pi | `$IMU,t,ax,ay,az,gx,gy,gz*HH` | t: ms; diğerleri ham değer (±2 g → 16384 LSB/g; ±250 °/s → 131 LSB/(°/s)) |
| Pi → ESP32 | `$LED,0\|1*HH` | GPIO4 LED'ini söndür / yak |
| Pi → ESP32 | `$HIZ,1..100*HH` | ölçüm hızı (Hz) |
| Pi → ESP32 | `$ESIK,1..89*HH` | **V1:** eğim eşiği (derece); ESP32 \|θ\| bu değeri aşınca GPIO5 LED'ini yakar, 5° altına inince söndürür |
| ESP32 → Pi | `$ACK,<komut>,<değer>*HH` | komut uygulandı (ör. `$ACK,ESIK,30`) |
| ESP32 → Pi | `$ERR,<neden>*HH` | `BICIM`, `CHECKSUM`, `KOMUT` veya `I2C` |

## Ölçüm sonuçları

Ayrıntılar ve şekiller: [`rapor/rapor.pdf`](rapor/rapor.pdf). Ham kayıtların açıklaması: [`olcum/README.md`](olcum/README.md).

| Ölçüm | Sonuç |
|---|---|
| 60 s kayıt (`alici.py --sure 60`) | 3001 geçerli satır, 50,01 Hz, hatalı satır 0; ESP32 zaman damgasında 3000 aralığın hepsi 20 ms |
| Komut–ACK (`--ack-testi 20`) | 20/20 yanıt; 19 × 3,4 ms, 1 × 3,5 ms |
| `hiz 10` / `hiz 50` | 9,9–10,1 Hz / 50,0 Hz |
| Açı doğruluğu (0° / 45° / 90°) | +0,10° / 44,67° / 90,00° (hata ≤ 0,33°) |
| Histerezis, eşikte bekleme | histerezisli 1, tek eşik 11 LED değişimi (aynı kayıt) |
| Histerezis, geniş salınım | histerezisli 7, tek eşik 8 LED değişimi (aynı kayıt) |

## Dosyalar

| Dosya | İçerik |
|---|---|
| `esp32/main/main.c` | Ölçüm görevi (`olcum_gorevi`, `xTaskDelayUntil`), alma görevi (`alma_gorevi`, daha yüksek öncelik), komut işleme, MPU-6050 sürücüsü; sensör yoksa sentetik veri |
| `pi/protokol.py` | `checksum`, `kodla`, `coz`, `imu_coz` |
| `pi/alici.py` | Satırları okur, doğrular, CSV'ye yazar, komut gönderir, hatalı satırları sayar |
| `pi/sim_esp32.py` | ESP32 benzetici (sanal seri port) |
| `pi/egim_alarmi.py` | V1: eğim hesabı, ortalama süzgeç, histerezisli alarm, `$ESIK` ve `$LED` komutları, olay günlüğü |
| `pi/histerezis_karsilastir.py` | Kaydedilmiş bir eğim kaydını histerezisli ve tek eşikli alarmdan geçirip LED değişimlerini sayar |
| `olcum/` | Raporda kullanılan ham kayıtlar ve program çıktıları (`olcum/README.md`) |
| `rapor/rapor.pdf` | Vize raporu; şekiller `rapor/sekiller/`, çizim betiği `rapor/sekil_ciz.py` |
