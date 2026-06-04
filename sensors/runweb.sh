#!/bin/bash
# MPU6050 web panosunu kalici (detached) baslatir. sudo ile calistir:
#   echo xilinx | sudo -S bash runweb.sh
cd /home/xilinx/neo_gps/sensors || exit 1
pkill -f mpu_web.py 2>/dev/null
sleep 1
setsid python3 -u mpu_web.py >/tmp/mpu_web.log 2>&1 </dev/null &
sleep 3
echo "PID: $(pgrep -f mpu_web.py || echo yok)"
echo "--- log ---"
cat /tmp/mpu_web.log
