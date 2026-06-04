#!/bin/sh
# PYNQ kartinda GPS overlay + neo_gps_pynq.py kurulumu
# PC: http://192.168.2.10:8000  (neo_gps klasorunden http.server)
set -e
PC=http://192.168.2.10:8000
DIR=/home/xilinx/neo_gps
mkdir -p "$DIR" /lib/firmware

echo "[1/5] GPS bitstream indir..."
wget -q "$PC/output/gps_uart.bin" -O /lib/firmware/gps_uart.bin
wget -q "$PC/output/gps_uart.hwh" -O "$DIR/gps_uart.hwh" 2>/dev/null || true

echo "[2/5] FPGA yukle..."
echo gps_uart.bin > /sys/class/fpga_manager/fpga0/firmware
sleep 3
echo "FPGA: $(cat /sys/class/fpga_manager/fpga0/state)"

echo "[3/5] Script indir..."
wget -q "$PC/neo_gps_pynq.py" -O "$DIR/neo_gps_pynq.py"
wget -q "$PC/uart_probe.py" -O "$DIR/uart_probe.py" 2>/dev/null || true
chmod +x "$DIR"/*.py 2>/dev/null || true

echo "[4/5] Ag (sabit IP istege bagli)..."
ip addr add 192.168.2.99/24 dev eth0 2>/dev/null || true
ip link set eth0 up 2>/dev/null || true

echo "[5/5] GPS test (8 sn)..."
cd "$DIR"
python3 neo_gps_pynq.py --skip-overlay --test-only 2>&1 || true

echo ""
echo "============================================"
echo " Kurulum bitti."
echo "  sudo python3 $DIR/neo_gps_pynq.py --skip-overlay"
echo "  veya: sudo python3 $DIR/neo_gps_pynq.py --probe"
echo "============================================"
