# PYNQ-Z2 + NEO-6M GPS — Türkçe Rehber

## Donanım fotoğrafları

![Kurulum — PYNQ-Z2 + NEO-6M](gps_hardware_setup.png)

![Kablolama şeması](wiring_diagram.svg)

![NEO-6M modül](neo6m_module.png)

## Bağlantı tablosu

| GPS pini | PYNQ RPi header | Açıklama |
|----------|-----------------|----------|
| VCC | Pin 1 (3.3 V) | Besleme |
| GND | Pin 6 | Toprak |
| TX | **Pin 10** | GPS veri gönderir → FPGA okur |
| RX | **Pin 8** | FPGA yazar → GPS okur |

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

## Canlı çıktı örneği

Karttan alınan gerçek veri: [sample_live_output.json](sample_live_output.json)

```
fix: true · 8 uydu · 36.767°N 34.542°E · rakım 48 m
```

## Mimari

![Yazılım akışı](architecture.svg)

## Sık hatalar

**Bus error** — İki GPS programı aynı anda çalışıyor veya yanlış bitstream.

```bash
sudo pkill -f 'gps_web.py|neo_gps_pynq.py'
sudo rm -f /tmp/neo_gps_uart.lock
echo gps_uart.bin | sudo tee /sys/class/fpga_manager/fpga0/firmware
bash start_web.sh
```

**Fix yok** — Anteni açık gökyüzüne çevir; 1–2 dakika bekle.

**I2C testinden sonra GPS çalışmıyor** — `gps_uart.bin` tekrar yükle.

## Sürüm

**v1.0.0** — İlk kararlı sürüm. Detay: [CHANGELOG.md](../CHANGELOG.md)
