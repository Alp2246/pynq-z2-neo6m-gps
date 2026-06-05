#!/bin/bash
# Pencere 1: sadece web
cd /home/xilinx/neo_gps
sudo pkill -f 'gps_web.py' 2>/dev/null
sudo pkill -f 'neo_gps_pynq.py' 2>/dev/null
sleep 1
sudo rm -f /tmp/neo_gps_uart.lock
echo "Tarayici: http://192.168.2.99:8080"
echo "Durdurmak: Ctrl+C"
exec sudo python3 gps_web.py