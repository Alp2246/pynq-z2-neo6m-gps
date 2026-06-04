#!/usr/bin/env python3
"""
MPU6050 (GY-521) okuyucu - 6 eksen ivme + jiroskop.
I2C adres: 0x68 (AD0=GND) veya 0x69 (AD0=VCC).

PYNQ-Z2 baglanti (I2C, AXI GPIO bit-bang overlay 'i2c_gpio'):
  MPU6050 VCC -> 3.3V (Pin 1)   <-- 5V VERME! Modul pull-up'lari VCC'ye bagli.
  MPU6050 GND -> GND  (Pin 6)
  MPU6050 SDA -> Pin 3 (W18)
  MPU6050 SCL -> Pin 5 (W19)
  AD0/XDA/XCL/INT -> bos birak

Iki backend:
  1) AXI GPIO bit-bang (ONERILEN, kendi overlay'imiz):
       sudo python3 mpu6050.py --axi-gpio
       sudo python3 mpu6050.py --axi-gpio --scan
  2) Linux i2c-dev (eger imajda /dev/i2c-N varsa):
       python3 mpu6050.py --bus 0
       python3 mpu6050.py --scan

Once overlay'i yukle: setup_mpu6050.sh
"""

import argparse
import sys
import time

# MPU6050 register haritasi
PWR_MGMT_1   = 0x6B
SMPLRT_DIV   = 0x19
CONFIG       = 0x1A
GYRO_CONFIG  = 0x1B
ACCEL_CONFIG = 0x1C
ACCEL_XOUT_H = 0x3B
WHO_AM_I     = 0x75

ACCEL_SCALE = 16384.0  # +/-2g  -> LSB/g
GYRO_SCALE  = 131.0    # +/-250 deg/s -> LSB/(deg/s)


def s16(high, low):
    val = (high << 8) | low
    return val - 65536 if val >= 0x8000 else val


# ---------------- backend secimi ----------------
def open_smbus(bus_id):
    try:
        from smbus2 import SMBus
    except ImportError:
        from smbus import SMBus
    return SMBus(bus_id)


def scan_smbus():
    """smbus ile 0x68/0x69 tara, (bus, addr, who) listesi dondur."""
    try:
        from smbus2 import SMBus
    except ImportError:
        try:
            from smbus import SMBus
        except ImportError:
            return []
    found = []
    for bus_id in range(0, 4):
        try:
            bus = SMBus(bus_id)
        except Exception:
            continue
        for addr in (0x68, 0x69):
            try:
                who = bus.read_byte_data(addr, WHO_AM_I)
                found.append((bus_id, addr, who))
            except Exception:
                pass
        bus.close()
    return found


def open_axi_gpio(base):
    from axi_gpio_i2c import AxiGpioI2C
    return AxiGpioI2C(base=base)


# ---------------- MPU6050 islemleri (backend-agnostik) ----------------
def init_mpu(bus, addr):
    bus.write_byte_data(addr, PWR_MGMT_1, 0x00)   # uyandir
    time.sleep(0.1)
    bus.write_byte_data(addr, SMPLRT_DIV, 0x07)
    bus.write_byte_data(addr, CONFIG, 0x00)
    bus.write_byte_data(addr, GYRO_CONFIG, 0x00)  # +/-250 deg/s
    bus.write_byte_data(addr, ACCEL_CONFIG, 0x00) # +/-2g


def read_all(bus, addr):
    d = bus.read_i2c_block_data(addr, ACCEL_XOUT_H, 14)
    ax = s16(d[0], d[1]) / ACCEL_SCALE
    ay = s16(d[2], d[3]) / ACCEL_SCALE
    az = s16(d[4], d[5]) / ACCEL_SCALE
    temp = s16(d[6], d[7]) / 340.0 + 36.53
    gx = s16(d[8], d[9]) / GYRO_SCALE
    gy = s16(d[10], d[11]) / GYRO_SCALE
    gz = s16(d[12], d[13]) / GYRO_SCALE
    return ax, ay, az, temp, gx, gy, gz


def main():
    p = argparse.ArgumentParser(description="MPU6050 okuyucu")
    p.add_argument("--axi-gpio", action="store_true",
                   help="AXI GPIO bit-bang backend (kendi overlay'imiz)")
    p.add_argument("--base", type=lambda x: int(x, 0), default=0x41200000,
                   help="AXI GPIO taban adresi (--axi-gpio icin)")
    p.add_argument("--bus", type=int, default=None, help="Linux I2C bus no")
    p.add_argument("--addr", type=lambda x: int(x, 0), default=0x68)
    p.add_argument("--scan", action="store_true", help="adres tara, cik")
    args = p.parse_args()

    # ---- TARAMA ----
    if args.scan:
        if args.axi_gpio:
            i2c = open_axi_gpio(args.base)
            print(f"[INFO] AXI GPIO base=0x{args.base:08X} taraniyor...")
            found = i2c.scan()
            if not found:
                print("Cihaz yok. 3.3V/kablo/pull-up ve overlay'i kontrol et.")
            for a in found:
                who = "?"
                try:
                    who = f"0x{i2c.read_byte_data(a, WHO_AM_I):02X}"
                except Exception:
                    pass
                print(f"  0x{a:02X} ACK  WHO_AM_I={who}")
            i2c.close()
        else:
            print("I2C (smbus) taraniyor...")
            found = scan_smbus()
            if not found:
                print("MPU6050 yok. 'i2cdetect -l' ve kablolari kontrol et.")
            for bus_id, addr, who in found:
                print(f"  bus={bus_id} addr=0x{addr:02X} WHO_AM_I=0x{who:02X}")
        return

    # ---- BACKEND AC ----
    if args.axi_gpio:
        bus = open_axi_gpio(args.base)
        print(f"[INFO] AXI GPIO backend, base=0x{args.base:08X}")
    else:
        bus_id = args.bus
        if bus_id is None:
            found = scan_smbus()
            if not found:
                print("[HATA] MPU6050 yok. Overlay icin: --axi-gpio kullan, "
                      "veya once: python3 mpu6050.py --scan")
                sys.exit(1)
            bus_id, args.addr, _ = found[0]
            print(f"[INFO] Otomatik: bus={bus_id} addr=0x{args.addr:02X}")
        bus = open_smbus(bus_id)

    try:
        who = bus.read_byte_data(args.addr, WHO_AM_I)
        print(f"[INFO] WHO_AM_I=0x{who:02X} (0x68 beklenir)")
        init_mpu(bus, args.addr)
        print("[INFO] Okunuyor... Ctrl+C ile cik.\n")
        while True:
            ax, ay, az, temp, gx, gy, gz = read_all(bus, args.addr)
            print(
                f"ACC[g] x={ax:+.2f} y={ay:+.2f} z={az:+.2f} | "
                f"GYRO[d/s] x={gx:+7.1f} y={gy:+7.1f} z={gz:+7.1f} | "
                f"T={temp:.1f}C",
                end="\r",
            )
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n[INFO] Durduruldu.")
    finally:
        bus.close()


if __name__ == "__main__":
    main()
