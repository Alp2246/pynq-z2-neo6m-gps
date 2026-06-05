# PYNQ-Z2 + NEO-6M GPS — Türkçe Rehber

## Donanım

![Kurulum fotoğrafı](gps_hardware_setup.png)

| GPS pini | PYNQ RPi header | Not |
|----------|-----------------|-----|
| VCC | Pin 1 (3.3 V) | Kırmızı/turuncu |
| GND | Pin 6 | Siyah |
| TX | **Pin 10** | GPS veri gönderir → FPGA okur |
| RX | **Pin 8** | FPGA komut gönderir → GPS okur |

![NEO-6M modül](neo6m_module.png)

## Hızlı başlangıç

```bash
cd ~/neo_gps
echo gps_uart.bin | sudo tee /sys/class/fpga_manager/fpga0/firmware
cat /sys/class/fpga_manager/fpga0/state   # operating
bash start_web.sh
```

Tarayıcı: **http://192.168.2.99:8080**

## Web arayüzü

| Sekme | Ne gösterir? |
|-------|----------------|
| **Pano** | Harita, fix, koordinat, uydu SNR |
| **NMEA** | GGA/RMC/GSA/GSV/VTG/GLL — alan alan Türkçe açıklama |

## Sık hatalar

**Bus error** — İki GPS programı aynı anda çalışıyor veya yanlış bitstream yüklü.

```bash
sudo pkill -f 'gps_web.py|neo_gps_pynq.py'
sudo rm -f /tmp/neo_gps_uart.lock
echo gps_uart.bin | sudo tee /sys/class/fpga_manager/fpga0/firmware
bash start_web.sh
```

**Fix yok** — Anteni açık gökyüzüne çevir; 1–2 dakika bekle.

**I2C testinden sonra GPS çalışmıyor** — `i2c_gpio.bin` yerine tekrar `gps_uart.bin` yükle.

## PuTTY ile iki pencere

1. **Pencere 1:** `bash start_web.sh` (sadece web)
2. **Pencere 2:** `curl http://127.0.0.1:8080/data` (kontrol; `neo_gps_pynq.py` çalıştırma)
