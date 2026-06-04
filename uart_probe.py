#!/usr/bin/env python3
# AXI UART Lite donanim testi: IP canli mi, RX'e veri geliyor mu?
import mmap, os, time, sys

BASE = 0x42C00000
RX, TX, STAT, CTRL = 0x00, 0x04, 0x08, 0x0C

fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=BASE)

def r32(off):
    import struct
    return struct.unpack("<I", m[off:off+4])[0]
def w32(off, val):
    import struct
    m[off:off+4] = struct.pack("<I", val)

s = r32(STAT)
print("STAT reg = 0x%08X  (0xFFFFFFFF ya da hep ayni ise IP/adres SORUNLU)" % s)
print("CTRL reg = 0x%08X" % r32(CTRL))

# CTRL: RX+TX FIFO reset
w32(CTRL, 0x03); time.sleep(0.05); w32(CTRL, 0x00)
print("FIFO reset sonrasi STAT = 0x%08X" % r32(STAT))

# 6 saniye RX dinle
print("6 saniye RX dinleniyor (GPS TX -> Pin 10/Y6)...")
cnt = 0
sample = bytearray()
t0 = time.time()
while time.time() - t0 < 6.0:
    st = r32(STAT)
    if st & 0x01:  # RX valid
        b = r32(RX) & 0xFF
        cnt += 1
        if len(sample) < 80:
            sample.append(b)
    else:
        time.sleep(0.0005)

print("TOPLAM RX byte = %d" % cnt)
if cnt:
    try:
        txt = bytes(sample).decode("ascii", "replace")
    except Exception:
        txt = repr(bytes(sample))
    print("ILK BAYTLAR (hex):", " ".join("%02x" % x for x in sample))
    print("ILK BAYTLAR (ascii):", txt)
    if any(33 <= x <= 126 or x in (10,13) for x in sample) and sum(1 for x in sample if x in (36,)) >= 0:
        print("-> Okunabilir/NMEA benzeri ise baud DOGRU. Cogu cop ise baud YANLIS.")
else:
    print("-> HIC veri yok: GPS TX Pin10/Y6'ya bagli degil, GPS beslenmiyor, ya da IP RX hatti calismiyor.")

m.close(); os.close(fd)
