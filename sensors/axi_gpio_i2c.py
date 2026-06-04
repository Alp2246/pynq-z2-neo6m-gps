#!/usr/bin/env python3
"""
AXI GPIO uzerinden bit-bang I2C (master) - PYNQ-Z2 / Zynq-7020.

Mantik:
  - i2c_gpio overlay'i 2-bit, bidirectional bir AXI GPIO sunar.
      bit0 = SDA (RPi Pin 3 / W18)
      bit1 = SCL (RPi Pin 5 / W19)
  - Open-drain I2C: DATA register hep 0 kalir. Hatti '0' yapmak icin
    TRI bitini 0 (output) yapariz; '1' (serbest) icin TRI bitini 1 (input)
    yapariz -> harici pull-up (sensor modulunde 4.7k) hatti yukari ceker.
  - Hat seviyesi DATA register'dan okunur.

Linux device-tree / i2c-dev surucusu GEREKMEZ. /dev/mem MMIO ile calisir.
Bu, projede UART icin kullandigimiz /dev/mem yontemiyle ayni mantik.

Kullanim (modul):
  from axi_gpio_i2c import AxiGpioI2C
  i2c = AxiGpioI2C(base=0x41200000)
  i2c.write(0x68, [0x6B, 0x00])          # reg yaz
  data = i2c.read_reg(0x68, 0x3B, 14)    # reg'den oku

CLI:
  sudo python3 axi_gpio_i2c.py --scan     # bus tarama (0x03..0x77)
"""

import argparse
import mmap
import os
import time

# AXI GPIO register offsetleri (PG144, Channel 1)
GPIO_DATA = 0x0000
GPIO_TRI = 0x0004

SDA_BIT = 0x1  # bit0
SCL_BIT = 0x2  # bit1

DEFAULT_BASE = 0x41200000
MAP_SIZE = 0x1000

# I2C zamanlama. mmap erisimi zaten yavas; yine de yarim periyot bekleriz.
# 5 us -> ~100 kHz teorik ust sinir; pratikte cok daha yavas, sorun degil.
HALF = 5e-6


class AxiGpioI2C:
    def __init__(self, base=DEFAULT_BASE):
        self.base = base
        self._fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        self._map = mmap.mmap(
            self._fd, MAP_SIZE, mmap.MAP_SHARED,
            mmap.PROT_READ | mmap.PROT_WRITE, offset=base
        )
        # DATA = 0 (her zaman): output yapildiginda hat 0'a cekilir.
        self._wr(GPIO_DATA, 0x0)
        # Baslangic: iki hat da serbest (input -> pull-up ile yuksek)
        self._tri = SDA_BIT | SCL_BIT
        self._wr(GPIO_TRI, self._tri)
        time.sleep(0.001)

    # --- dusuk seviye register ---
    def _wr(self, off, val):
        self._map[off:off + 4] = (val & 0xFFFFFFFF).to_bytes(4, "little")

    def _rd(self, off):
        return int.from_bytes(self._map[off:off + 4], "little")

    # --- hat kontrolu (open-drain) ---
    def _sda_release(self):
        self._tri |= SDA_BIT
        self._wr(GPIO_TRI, self._tri)

    def _sda_low(self):
        self._tri &= ~SDA_BIT
        self._wr(GPIO_TRI, self._tri)

    def _scl_release(self):
        self._tri |= SCL_BIT
        self._wr(GPIO_TRI, self._tri)
        # clock stretching: kole SCL'i tutuyorsa serbest birakmasini bekle
        t0 = time.time()
        while not (self._rd(GPIO_DATA) & SCL_BIT):
            if time.time() - t0 > 0.01:
                break

    def _scl_low(self):
        self._tri &= ~SCL_BIT
        self._wr(GPIO_TRI, self._tri)

    def _read_sda(self):
        return 1 if (self._rd(GPIO_DATA) & SDA_BIT) else 0

    @staticmethod
    def _wait():
        time.sleep(HALF)

    # --- I2C protokol ilkelleri ---
    def _start(self):
        self._sda_release()
        self._scl_release()
        self._wait()
        self._sda_low()
        self._wait()
        self._scl_low()
        self._wait()

    def _repeated_start(self):
        self._sda_release()
        self._scl_release()
        self._wait()
        self._sda_low()
        self._wait()
        self._scl_low()
        self._wait()

    def _stop(self):
        self._sda_low()
        self._wait()
        self._scl_release()
        self._wait()
        self._sda_release()
        self._wait()

    def _write_bit(self, b):
        if b:
            self._sda_release()
        else:
            self._sda_low()
        self._wait()
        self._scl_release()
        self._wait()
        self._scl_low()
        self._wait()

    def _read_bit(self):
        self._sda_release()  # kole surebilsin
        self._wait()
        self._scl_release()
        self._wait()
        v = self._read_sda()
        self._scl_low()
        self._wait()
        return v

    def _write_byte(self, byte):
        """1 bayt yazar, ACK dondurur (True=ACK alindi)."""
        for i in range(8):
            self._write_bit((byte >> (7 - i)) & 1)
        ack = self._read_bit()  # 0 = ACK
        return ack == 0

    def _read_byte(self, ack):
        """1 bayt okur; ack=True ise ACK (devam), False ise NACK (son bayt)."""
        val = 0
        for _ in range(8):
            val = (val << 1) | self._read_bit()
        self._write_bit(0 if ack else 1)
        return val

    # --- yuksek seviye API ---
    def write(self, addr, data):
        """addr cihazina data (liste/bytes) yazar."""
        self._start()
        if not self._write_byte((addr << 1) | 0):
            self._stop()
            raise IOError(f"0x{addr:02X} ACK vermedi (yazma adresi)")
        for d in data:
            if not self._write_byte(d & 0xFF):
                self._stop()
                raise IOError(f"0x{addr:02X} veri ACK vermedi (0x{d:02X})")
        self._stop()

    def read_reg(self, addr, reg, length):
        """addr cihazindan reg'den baslayarak length bayt okur."""
        self._start()
        if not self._write_byte((addr << 1) | 0):
            self._stop()
            raise IOError(f"0x{addr:02X} ACK vermedi (reg ayari)")
        self._write_byte(reg & 0xFF)
        self._repeated_start()
        if not self._write_byte((addr << 1) | 1):
            self._stop()
            raise IOError(f"0x{addr:02X} ACK vermedi (okuma adresi)")
        out = []
        for i in range(length):
            out.append(self._read_byte(ack=(i < length - 1)))
        self._stop()
        return out

    def read_byte_data(self, addr, reg):
        return self.read_reg(addr, reg, 1)[0]

    def write_byte_data(self, addr, reg, val):
        self.write(addr, [reg, val])

    def read_i2c_block_data(self, addr, reg, length):
        return self.read_reg(addr, reg, length)

    def ping(self, addr):
        """addr cihazi ACK veriyor mu? (adres + dur)"""
        self._start()
        ack = self._write_byte((addr << 1) | 0)
        self._stop()
        return ack

    def scan(self, lo=0x03, hi=0x77):
        found = []
        for a in range(lo, hi + 1):
            try:
                if self.ping(a):
                    found.append(a)
            except Exception:
                pass
        return found

    def close(self):
        try:
            self._sda_release()
            self._scl_release()
        finally:
            self._map.close()
            os.close(self._fd)


def main():
    p = argparse.ArgumentParser(description="AXI GPIO bit-bang I2C")
    p.add_argument("--base", type=lambda x: int(x, 0), default=DEFAULT_BASE,
                   help="AXI GPIO taban adresi (varsayilan 0x41200000)")
    p.add_argument("--scan", action="store_true", help="I2C bus tara")
    args = p.parse_args()

    i2c = AxiGpioI2C(base=args.base)
    try:
        if args.scan:
            print(f"[INFO] base=0x{args.base:08X} taraniyor (0x03..0x77)...")
            found = i2c.scan()
            if not found:
                print("Cihaz bulunamadi. Kablo/3.3V/pull-up kontrol et.")
            for a in found:
                print(f"  0x{a:02X} ACK")
            print("MPU6050 -> 0x68 (AD0=GND) veya 0x69 (AD0=VCC)")
    finally:
        i2c.close()


if __name__ == "__main__":
    main()
