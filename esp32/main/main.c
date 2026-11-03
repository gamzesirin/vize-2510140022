/*
 * İleri Gömülü Sistemler – Vize projesi, ESP32-S3 tarafı
 * Gamze Şirin (2510140022)
 *
 * MPU-6050'yi I²C ile sabit aralıkla (varsayılan 50 Hz) okur, her ölçümü UART1
 * üzerinden $IMU satırı olarak Raspberry Pi'ye gönderir ve Pi'den gelen komutları
 * uygulayıp $ACK veya $ERR ile yanıtlar.
 *
 * Bağlantılar
 *   GPIO17 (UART1 TX)  -> Pi pin 10 (GPIO15, RXD)
 *   GPIO18 (UART1 RX)  <- Pi pin 8  (GPIO14, TXD)
 *   GND                -> Pi pin 6
 *   3V3 / GND          -> MPU-6050 VCC / GND
 *   GPIO8 / GPIO9      -> MPU-6050 SDA / SCL (I²C, 400 kHz)
 *   GPIO4              -> 330 Ω -> LED -> GND
 *
 * Protokol (her satır $GOVDE*HH\r\n, HH: $ ile * arasındaki karakterlerin XOR'u)
 *   ESP32 -> Pi : $IMU,t,ax,ay,az,gx,gy,gz   (t: ms, diğerleri ham sensör değeri)
 *                 $ACK,<komut>,<değer>        $ERR,<BICIM|CHECKSUM|KOMUT|I2C>
 *   Pi -> ESP32 : $LED,0|1                    $HIZ,1..100
 */
#include <ctype.h>
#include <math.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

/* ---- Donanım ---------------------------------------------------------- */
#define UART_PORT        UART_NUM_1
#define UART_TX_PIN      17
#define UART_RX_PIN      18
#define UART_BAUD        115200
#define UART_TAMPON      2048

#define I2C_SDA_PIN      8
#define I2C_SCL_PIN      9
#define I2C_HIZ_HZ       400000
#define I2C_ZAMAN_ASIMI  20          /* ms */

#define LED_PIN          GPIO_NUM_4

/* ---- MPU-6050 registerları ---------------------------------------------- */
#define MPU_ADRES        0x68
#define REG_CONFIG       0x1A        /* sayısal alçak geçiren süzgeç */
#define REG_GYRO_CONFIG  0x1B
#define REG_ACCEL_CONFIG 0x1C
#define REG_ACCEL_XOUT_H 0x3B        /* 0x3B..0x48: ivme, sıcaklık, dönü (14 bayt) */
#define REG_PWR_MGMT_1   0x6B
#define REG_WHO_AM_I     0x75

/* ---- Görevler ----------------------------------------------------------- */
#define VARSAYILAN_HZ    50
#define OLCUM_ONCELIK    5
#define ALMA_ONCELIK     6           /* komutlar ölçüm sürerken de hemen işlensin */
#define SATIR_UZUNLUK    96

static const char *TAG = "vize";

static i2c_master_bus_handle_t i2c_yolu;
static i2c_master_dev_handle_t mpu;
static bool sensor_var;
static SemaphoreHandle_t uart_kilit;         /* iki görev aynı UART'a yazar */
static volatile uint32_t olcum_hz = VARSAYILAN_HZ;

/* ---- Protokol --------------------------------------------------------- */

/* $ ile * arasındaki karakterlerin XOR'u */
static uint8_t checksum(const char *govde)
{
    uint8_t x = 0;
    while (*govde)
        x ^= (uint8_t)*govde++;
    return x;
}

/* Gövdeyi $...*HH\r\n biçiminde gönderir */
static void satir_gonder(const char *govde)
{
    char satir[SATIR_UZUNLUK + 8];
    int n = snprintf(satir, sizeof(satir), "$%s*%02X\r\n", govde, checksum(govde));
    xSemaphoreTake(uart_kilit, portMAX_DELAY);
    uart_write_bytes(UART_PORT, satir, (size_t)n);
    xSemaphoreGive(uart_kilit);
}

/* ---- MPU-6050 --------------------------------------------------------- */

static esp_err_t mpu_yaz(uint8_t reg, uint8_t deger)
{
    uint8_t paket[2] = { reg, deger };
    return i2c_master_transmit(mpu, paket, sizeof(paket), I2C_ZAMAN_ASIMI);
}

static esp_err_t mpu_oku(uint8_t reg, uint8_t *veri, size_t n)
{
    return i2c_master_transmit_receive(mpu, &reg, 1, veri, n, I2C_ZAMAN_ASIMI);
}

/* Sensörü bulur ve ayarlar; bulunamazsa false döner (sentetik veri kullanılır) */
static bool mpu_baslat(void)
{
    const i2c_master_bus_config_t yol_ayari = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = I2C_SDA_PIN,
        .scl_io_num = I2C_SCL_PIN,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    ESP_ERROR_CHECK(i2c_new_master_bus(&yol_ayari, &i2c_yolu));

    if (i2c_master_probe(i2c_yolu, MPU_ADRES, I2C_ZAMAN_ASIMI) != ESP_OK) {
        ESP_LOGW(TAG, "MPU-6050 0x%02X adresinde yanıt vermedi: sentetik veri gönderilecek", MPU_ADRES);
        return false;
    }

    const i2c_device_config_t cihaz_ayari = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = MPU_ADRES,
        .scl_speed_hz = I2C_HIZ_HZ,
    };
    ESP_ERROR_CHECK(i2c_master_bus_add_device(i2c_yolu, &cihaz_ayari, &mpu));

    uint8_t kimlik = 0;
    if (mpu_oku(REG_WHO_AM_I, &kimlik, 1) != ESP_OK) {
        ESP_LOGW(TAG, "WHO_AM_I okunamadı: sentetik veri gönderilecek");
        return false;
    }
    /* 0x68: MPU-6050. 0x70: aynı register haritasını kullanan MPU-6500 (bazı GY-521 modülleri) */
    if (kimlik == 0x68 || kimlik == 0x70)
        ESP_LOGI(TAG, "MPU-6050 bulundu, WHO_AM_I = 0x%02X%s", kimlik,
                 kimlik == 0x70 ? " (MPU-6500 uyumlu yonga)" : "");
    else
        ESP_LOGW(TAG, "Beklenmeyen WHO_AM_I = 0x%02X, yine de devam ediliyor", kimlik);

    /* Uykudan çıkar (saat: X ekseni jiroskop PLL), süzgeç ~44 Hz, ±250 °/s, ±2 g */
    const uint8_t ayarlar[][2] = {
        { REG_PWR_MGMT_1, 0x01 },
        { REG_CONFIG, 0x03 },
        { REG_GYRO_CONFIG, 0x00 },
        { REG_ACCEL_CONFIG, 0x00 },
    };
    for (size_t i = 0; i < sizeof(ayarlar) / sizeof(ayarlar[0]); i++) {
        if (mpu_yaz(ayarlar[i][0], ayarlar[i][1]) != ESP_OK) {
            ESP_LOGW(TAG, "Register 0x%02X yazılamadı: sentetik veri gönderilecek", ayarlar[i][0]);
            return false;
        }
    }
    vTaskDelay(pdMS_TO_TICKS(50));   /* sensörün ilk ölçümü hazırlaması için */
    return true;
}

/* ivme x,y,z ve dönü x,y,z ham değerleri */
static bool mpu_olc(int16_t d[6])
{
    uint8_t b[14];
    if (mpu_oku(REG_ACCEL_XOUT_H, b, sizeof(b)) != ESP_OK)
        return false;
    d[0] = (int16_t)((b[0] << 8) | b[1]);
    d[1] = (int16_t)((b[2] << 8) | b[3]);
    d[2] = (int16_t)((b[4] << 8) | b[5]);
    /* b[6], b[7]: sıcaklık, kullanılmıyor */
    d[3] = (int16_t)((b[8] << 8) | b[9]);
    d[4] = (int16_t)((b[10] << 8) | b[11]);
    d[5] = (int16_t)((b[12] << 8) | b[13]);
    return true;
}

/* Sensör yokken: y ekseni etrafında 10 s periyotla ±40° sallanan bir modül gibi davranır */
static void sentetik_olc(int16_t d[6], uint32_t t_ms)
{
    const float pi = 3.14159265f;
    float aci = 40.0f * sinf(2.0f * pi * (float)t_ms / 10000.0f) * pi / 180.0f;
    d[0] = (int16_t)(16384.0f * sinf(aci));
    d[1] = 0;
    d[2] = (int16_t)(16384.0f * cosf(aci));
    d[3] = 0;
    d[4] = (int16_t)(131.0f * 40.0f * 2.0f * pi / 10.0f * cosf(2.0f * pi * (float)t_ms / 10000.0f));
    d[5] = 0;
}

/* ---- Görevler ----------------------------------------------------------- */

/* Sabit aralıkla ölçüm alıp $IMU satırı gönderir */
static void olcum_gorevi(void *arg)
{
    (void)arg;
    TickType_t son_uyanma = xTaskGetTickCount();
    uint32_t i2c_hata = 0;

    for (;;) {
        int16_t d[6];
        uint32_t t_ms = (uint32_t)(esp_timer_get_time() / 1000);
        bool tamam = true;

        if (sensor_var)
            tamam = mpu_olc(d);
        else
            sentetik_olc(d, t_ms);

        if (tamam) {
            char govde[SATIR_UZUNLUK];
            snprintf(govde, sizeof(govde), "IMU,%lu,%d,%d,%d,%d,%d,%d",
                     (unsigned long)t_ms, d[0], d[1], d[2], d[3], d[4], d[5]);
            satir_gonder(govde);
        } else if (i2c_hata++ % 50 == 0) {
            satir_gonder("ERR,I2C");   /* hata sürerse en fazla 50 ölçümde bir bildirilir */
        }

        /* xTaskDelayUntil: bekleme süresi ölçümün ne kadar sürdüğünden bağımsız */
        TickType_t periyot = pdMS_TO_TICKS(1000 / olcum_hz);
        xTaskDelayUntil(&son_uyanma, periyot > 0 ? periyot : 1);
    }
}

/* Gelen tek bir satırı ($GOVDE*HH, \r\n'siz) doğrular ve uygular */
static void komut_isle(char *satir)
{
    char *yildiz = strrchr(satir, '*');
    if (satir[0] != '$' || yildiz == NULL || strlen(yildiz) != 3 ||
        !isxdigit((unsigned char)yildiz[1]) || !isxdigit((unsigned char)yildiz[2])) {
        satir_gonder("ERR,BICIM");
        return;
    }
    unsigned long gelen = strtoul(yildiz + 1, NULL, 16);
    *yildiz = '\0';
    char *govde = satir + 1;
    if (gelen != checksum(govde)) {
        satir_gonder("ERR,CHECKSUM");
        return;
    }

    /* govde: KOMUT,DEGER */
    char *deger_yazi = strchr(govde, ',');
    if (deger_yazi != NULL)
        *deger_yazi++ = '\0';
    const char *komut = govde;

    bool led = strcmp(komut, "LED") == 0;
    bool hiz = strcmp(komut, "HIZ") == 0;
    if (!led && !hiz) {
        satir_gonder("ERR,KOMUT");
        return;
    }

    char *son = NULL;
    long deger = (deger_yazi != NULL) ? strtol(deger_yazi, &son, 10) : 0;
    bool sayi = deger_yazi != NULL && *deger_yazi != '\0' && *son == '\0';

    if (led && sayi && (deger == 0 || deger == 1)) {
        gpio_set_level(LED_PIN, (uint32_t)deger);
    } else if (hiz && sayi && deger >= 1 && deger <= 100) {
        olcum_hz = (uint32_t)deger;
    } else {
        satir_gonder("ERR,BICIM");
        return;
    }

    char cevap[32];
    snprintf(cevap, sizeof(cevap), "ACK,%s,%ld", komut, deger);
    satir_gonder(cevap);
}

/* UART'tan bayt bayt okur, \n gelince satırı işler */
static void alma_gorevi(void *arg)
{
    (void)arg;
    char satir[SATIR_UZUNLUK];
    size_t n = 0;
    bool tasti = false;

    for (;;) {
        uint8_t c;
        if (uart_read_bytes(UART_PORT, &c, 1, portMAX_DELAY) != 1)
            continue;
        if (c == '\r')
            continue;
        if (c == '\n') {
            satir[n] = '\0';
            if (tasti)
                satir_gonder("ERR,BICIM");
            else if (n > 0)
                komut_isle(satir);
            n = 0;
            tasti = false;
            continue;
        }
        if (n < sizeof(satir) - 1)
            satir[n++] = (char)c;
        else
            tasti = true;   /* satır çok uzun: sonuna kadar atılır */
    }
}

/* ---- Başlangıç ---------------------------------------------------------- */

void app_main(void)
{
    const gpio_config_t led_ayari = {
        .pin_bit_mask = 1ULL << LED_PIN,
        .mode = GPIO_MODE_OUTPUT,
    };
    ESP_ERROR_CHECK(gpio_config(&led_ayari));
    gpio_set_level(LED_PIN, 0);

    const uart_config_t uart_ayari = {
        .baud_rate = UART_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(UART_PORT, UART_TAMPON, UART_TAMPON, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(UART_PORT, &uart_ayari));
    ESP_ERROR_CHECK(uart_set_pin(UART_PORT, UART_TX_PIN, UART_RX_PIN,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));

    uart_kilit = xSemaphoreCreateMutex();
    sensor_var = mpu_baslat();

    ESP_LOGI(TAG, "UART1 TX=GPIO%d RX=GPIO%d, %d baud, ölçüm %lu Hz, kaynak: %s",
             UART_TX_PIN, UART_RX_PIN, UART_BAUD, (unsigned long)olcum_hz,
             sensor_var ? "MPU-6050" : "sentetik");

    xTaskCreate(alma_gorevi, "alma_gorevi", 4096, NULL, ALMA_ONCELIK, NULL);
    xTaskCreate(olcum_gorevi, "olcum_gorevi", 4096, NULL, OLCUM_ONCELIK, NULL);
}
