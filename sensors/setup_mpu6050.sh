#!/bin/sh
# PYNQ-Z2 kartinda MPU6050 (AXI GPIO bit-bang I2C) kurulum + test.
#
# PC tarafinda (neo_gps klasorunde) basit http sunucu calismali:
#   python -m http.server 8000
# PC IP'ni asagiya yaz (varsayilan 192.168.2.10) veya parametre ver:
#   sh setup_mpu6050.sh 192.168.1.50
set -e
PC_IP="${1:-192.168.2.10}"
PC="http://$PC_IP:8000"
DIR=/home/xilinx/neo_gps/sensors
mkdir -p "$DIR" /lib/firmware

echo "[1/4] I2C overlay (bitstream) indir... ($PC)"
wget -q "$PC/output/i2c_gpio.bin" -O /lib/firmware/i2c_gpio.bin
wget -q "$PC/output/i2c_gpio.hwh" -O "$DIR/i2c_gpio.hwh" 2>/dev/null || true

echo "[2/4] FPGA yukle..."
echo i2c_gpio.bin > /sys/class/fpga_manager/fpga0/firmware
sleep 2
echo "FPGA durum: $(cat /sys/class/fpga_manager/fpga0/state)"

echo "[3/4] Python dosyalari indir..."
wget -q "$PC/sensors/axi_gpio_i2c.py" -O "$DIR/axi_gpio_i2c.py"
wget -q "$PC/sensors/mpu6050.py"      -O "$DIR/mpu6050.py"
chmod +x "$DIR"/*.py 2>/dev/null || true

echo "[4/4] I2C tarama (0x68/0x69 bekleniyor)..."
cd "$DIR"
python3 mpu6050.py --axi-gpio --scan || true

echo ""
echo "============================================"
echo " Kurulum bitti. Surekli okuma icin:"
echo "   cd $DIR"
echo "   sudo python3 mpu6050.py --axi-gpio"
echo ""
echo " Sadece bus tarama:"
echo "   sudo python3 axi_gpio_i2c.py --scan"
echo "============================================"
