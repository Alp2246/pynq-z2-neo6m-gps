# Changelog

## [1.0.0] — 2026-06-05

First stable release: live GPS on PYNQ-Z2 with FPGA UART overlay and web dashboard.

### Added

- **gps_web.py** — live map, fix badge, satellite SNR bars, NMEA decoder tab (GGA/RMC/GSA/GSV/VTG/GLL)
- **neo_gps_pynq.py** — MMIO UART reader, probe mode, process lock (bus error fix)
- **start_web.sh** — one-command dashboard start on the board
- Pre-built **gps_uart.bin** bitstream (AXI UART Lite @ `0x42C00000`, 9600 baud, V6/Y6)
- Hardware photos and wiring / architecture SVG diagrams in `docs/`
- Turkish setup guide: `docs/README_TR.md`
- Live API sample capture: `docs/sample_live_output.json`

### Verified (live test)

- Board: PYNQ-Z2 @ 192.168.2.99
- Fix: 8 satellites, ~36.77°N 34.54°E (Mersin area)
- FPGA state: `operating`
- Dashboard: http://192.168.2.99:8080

### Also in repository

- MPU6050 I2C overlay and IMU web dashboard (`sensors/`)
