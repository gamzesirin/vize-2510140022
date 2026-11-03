# Ölçüm kayıtları

Tüm kayıtlar 03.11.2026'da Raspberry Pi'de alındı. `.txt` dosyaları programın ekran çıktısıdır (`| tee`), `.csv` dosyaları programın kendi yazdığı kayıtlardır.

## Dosya biçimleri

| Dosya | Sütunlar |
|---|---|
| `hiz_60s.csv`, `ack_20.csv` (`alici.py`) | `pi_zaman_s` (Pi saati, s), `t_ms` (ESP32 saati, ms), `ax_g ay_g az_g` (g), `gx_dps gy_dps gz_dps` (°/s) |
| `egim_<zaman>.csv` (`egim_alarmi.py`) | `pi_zaman_s`, `t_ms`, `aci_derece` (θ = atan2(ax, az)), `ort_aci_derece` (son 10 örnek), `alarm` (0/1) |
| `aci_dogrulugu.csv` | `gercek_derece`, `ort_derece`, `ss_derece`, `min`, `max`, `n` |
| `alarm_olaylari.csv` | `zaman` (Pi saati), `t_ms`, `ort_aci_derece`, `olay` (`ALARM_BASLADI` / `ALARM_BITTI`), `mod`, `ust`, `alt` |
| `histerezis_karsilastirma.csv` | `kayit`, `mod`, `ust`, `alt`, `pencere`, `ornek`, `sure_s`, `led_degisim`, `kisa_durum` (< 0,5 s), `alarmda_s` |

## Dosyalar ve rapordaki yerleri

| Dosya | Ne | Rapor |
|---|---|---|
| `hiz_60s.csv`, `hiz_60s.txt` | 60 s kayıt, sensör düz: 3001 satır, 50,01 Hz, 0 hatalı | 5.1 |
| `ack_20.csv`, `ack_20.txt` | 20 `$LED` komutunun ACK süresi | 5.2 |
| `aci_dogrulugu.csv`, `aci_olcum.txt` | 0°, 45° (3 deneme), 90° ölçümleri | 5.4, Tablo 3 |
| `egim_20261103_192125.csv` | 0° ham kaydı | 5.4 |
| `egim_20261103_192236.csv`, `egim_20261103_192303.csv` | 45°, kitap elle tutulurken (std. sapma 2,25° ve 1,70°) | 5.4 |
| `egim_20261103_192325.csv` | 45°, kitap sabitken (raporda kullanılan) | 5.4 |
| `egim_20261103_192502.csv` | 90° ham kaydı | 5.4 |
| `aci_gecersiz_denemeler.csv`, `aci_gecersiz_denemeler.txt` | Yanlış eksende eğme ve yanlış etiket nedeniyle geçersiz sayılan 14 deneme | 6 |
| `egim_20261103_184706.csv` | Üç turluk alarm denemesi (196 s, 9810 örnek; örnek kaybı kontrolü) | 5.1, 5.5 |
| `alarm_olaylari.csv` | Bütün `egim_alarmi.py` çalıştırmalarının alarm olayları (V1 olay günlüğü) | 5.5 |
| `egim_20261103_192848.csv`, `histerezis_var_salinim.txt` | Senaryo 1, geniş salınım; canlı mod histerezisli | 5.5, Şekil 2c |
| `egim_20261103_193449.csv`, `histerezis_yok_esikte.txt` | Senaryo 2, eşikte bekleme; canlı mod tek eşik | 5.5, Şekil 2a–b |
| `histerezis_karsilastirma.csv`, `histerezis_karsilastirma.txt` | `histerezis_karsilastir.py` ile iki kaydın iki moddan geçirilmesi | 5.5 |
| `egim_20261103_192655.csv` | Histerezisli, kart 31–33°'de sabit tutuldu (eşik geçilmediği için karşılaştırmada kullanılmadı) | – |
| `egim_20261103_193207.csv`, `histerezis_yok_salinim.txt` | Tek eşik, kart 32–34°'de sabit tutuldu; adı "salınım" olsa da kart sallanmadı, karşılaştırmada kullanılmadı | – |

## Yeniden hesaplama

```
cd pi
python histerezis_karsilastir.py ../olcum/egim_20261103_192848.csv ../olcum/egim_20261103_193449.csv
python ../rapor/sekil_ciz.py ../olcum ../rapor/sekiller      # matplotlib gerekir
```
