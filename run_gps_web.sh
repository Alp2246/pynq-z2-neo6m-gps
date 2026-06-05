#!/bin/bash
# PYNQ-Z2 GPS web panosu
set -e
cd "$(dirname "$0")"
BIN=gps_uart.bin
if [ ! -f "$BIN" ]; then
    echo "[HATA] $BIN yok."
    exit 1
fi
echo "[1/2] Bitstream..."
sudo cp "$BIN" /lib/firmware/gps_uart.bin
echo gps_uart.bin | sudo tee /sys/class/fpga_manager/fpga0/firmware > /dev/null
sleep 2
echo "      state: $(cat /sys/class/fpga_manager/fpga0/state)"
echo "[2/2] Web panosu http://192.168.2.99:8080"
exec sudo python3 gps_web.py --skip-overlay
