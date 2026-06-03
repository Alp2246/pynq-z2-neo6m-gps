#!/bin/bash
# PYNQ-Z2 NEO-6M GPS - RPi header (Pin 8/10) bitstream + terminal okuma
set -e
cd "$(dirname "$0")"

BIN=gps_uart.bin

if [ ! -f "$BIN" ]; then
    echo "[HATA] $BIN yok. Karta yukleyin."
    exit 1
fi

echo "[1/2] Bitstream yukleniyor ($BIN)..."
sudo cp "$BIN" /lib/firmware/gps_uart.bin
echo gps_uart.bin | sudo tee /sys/class/fpga_manager/fpga0/firmware > /dev/null
sleep 2
echo "      state: $(cat /sys/class/fpga_manager/fpga0/state)"

echo "[2/2] GPS okuma basliyor (Ctrl+C ile cik)..."
exec sudo python3 neo_gps_pynq.py --skip-overlay --no-sudo
