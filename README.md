# PYNQ-Z2 + NEO-6M GPS

Ublox **NEO-6M** GPS modülünü **PYNQ-Z2** (Zynq-7020) FPGA kartı ile okuyan, koordinatları
terminalde ve **canlı web panosunda** (harita + uydu sinyalleri) gösteren proje.

GPS modülü, FPGA içinde oluşturulan bir **AXI UART Lite** çekirdeğine (9600 baud) Raspberry Pi
header üzerinden bağlanır. Yazılım, UART register'larını `/dev/mem` üzerinden okuyarak NMEA
cümlelerini ayrıştırır — PYNQ Overlay API'sine ihtiyaç duymaz.

> Web panosu: harita üzerinde canlı konum, fix durumu ve uydu sinyal (SNR) çubukları.

## Özellikler

- FPGA tabanlı donanım UART (AXI UART Lite @ `0x42C00000`, 9600 baud)
- `/dev/mem` (MMIO) ile doğrudan register erişimi — PYNQ Overlay gerektirmez
- NMEA ayrıştırma: `GGA`, `RMC` (konum), `GSV` (uydu sinyalleri)
- Canlı web panosu: Leaflet harita + konum + uydu SNR çubukları
- Terminal okuyucu + tanılama modları (probe, loopback, tx-test)
- `fpga_manager` ile `.bin` yükleme (Overlay API'siz)

## Donanım

| Parça | Açıklama |
|-------|----------|
| PYNQ-Z2 | Zynq XC7Z020, PYNQ 2.7 imajı |
| Ublox NEO-6M | GY-NEO6MV2 modülü, 9600 baud |
| Bağlantı | Raspberry Pi header (40 pin) |

### Kablo bağlantısı (Raspberry Pi header)

GPS ile FPGA UART **çapraz** bağlanır:

| GPS pini | RPi header pin | Zynq | Açıklama |
|----------|----------------|------|----------|
| VCC | **Pin 1** (3.3V) | — | Güç |
| GND | **Pin 6** | — | Toprak |
| TX | **Pin 10** | Y6 | GPS gönderir → FPGA RX |
| RX | **Pin 8** | V6 | FPGA TX → GPS alır |

> **Önemli:** Pin atamaları resmi PYNQ-Z2 `base.xdc` ile doğrulanmıştır
> (Pin 8 = `V6`, Pin 10 = `Y6`). Kabloları **kart kapalıyken** tak/çıkar.

## Hızlı başlangıç

### 1. Bitstream'i karta kopyala

`output/` içindeki dosyaları kartın `~/jupyter_notebooks/` klasörüne yükle:

- `gps_uart.bin` — fpga_manager bitstream
- `gps_uart.hwh` — donanım handoff (XML)
- `neo_gps_pynq.py`, `gps_web.py`, `run_gps.sh`, `run_gps_web.sh`

### 2. Terminal okuma

```bash
cd ~/jupyter_notebooks
bash run_gps.sh
```

Fix alınınca:

```
Enlem : 41.015137 derece
Boylam: 28.979530 derece
```

### 3. Canlı web panosu

```bash
bash run_gps_web.sh
```

Sonra PC tarayıcıdan aç: **`http://<KART_IP>:8080`**
(harita karoları için PC'nin internete bağlı olması yeterli; kartın internete ihtiyacı yok).

## Tanılama modları

```bash
# 10 sn ham byte + register dökümü
sudo python3 neo_gps_pynq.py --skip-overlay --probe --no-sudo

# 8 sn byte sayım testi
sudo python3 neo_gps_pynq.py --skip-overlay --test-only --no-sudo

# Loopback (GPS çıkar, Pin 8 ↔ Pin 10 jumper)
sudo python3 neo_gps_pynq.py --skip-overlay --loopback --no-sudo
```

## Bitstream'i yeniden derleme (Vivado 2022.2)

```bat
cd vivado
run_build.bat
```

Bu script otomatik olarak: Zynq PS7 + AXI UART Lite blok tasarımı kurar, `rpi_uart.xdc`
kısıtlarını uygular, sentez + implementasyon çalıştırır, bitstream ve `fpga_manager` `.bin`
dosyasını `output/` klasörüne üretir.

> PMOD A pinleri için alternatif: `run_build_pmod.bat` (`pmoda_uart.xdc`, `gps_uart_pmod.*`).

## Proje yapısı

```
neo_gps/
├── neo_gps_pynq.py        # Ana GPS okuyucu (MMIO UART, NMEA parse)
├── gps_web.py             # Canlı web panosu (HTTP + Leaflet)
├── neo_gps.py             # Windows/COM (USB-TTL) sürümü
├── run_gps.sh             # Bitstream yükle + terminal okuma
├── run_gps_web.sh         # Bitstream yükle + web panosu
├── output/                # Üretilmiş bitstream'ler (.bit .bin .hwh)
└── vivado/
    ├── build_gps_uart.tcl      # Otomatik Vivado build (RPi)
    ├── build_gps_uart_pmod.tcl # Otomatik Vivado build (PMOD A)
    ├── rpi_uart.xdc            # Pin kısıtları (Pin 8/10 = V6/Y6)
    ├── pmoda_uart.xdc          # Pin kısıtları (PMOD A = Y18/Y19)
    └── run_build*.bat          # Build başlatıcılar
```

## Notlar

- PYNQ **2.7** imajı kullanılmıştır (3.x'te overlay yükleme sorunları yaşandı).
- Bitstream `.bit` yerine byte-swapped `.bin` ile `fpga_manager`'a yüklenir.
- Kart açıkken GPS kablosu oynatmak `Bus error` / AXI abort'a yol açabilir.

## Lisans

MIT — bkz. [LICENSE](LICENSE).
