#!/usr/bin/env python3
"""
PYNQ-Z2 + NEO-6M (RPi header Pin 8/10, UART, 9600 baud).

Tek komut (PYNQ kartinda):
  sudo python3 neo_gps_pynq.py

veya:
  bash run_gps.sh
"""

import argparse
import mmap
import os
import shutil
import struct
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

BAUD_RATE = 9600
DEFAULT_OVERLAY = "gps_uart.bit"
UART_BASE_ADDR = 0x42C00000
UART_MAP_SIZE = 0x1000
PYNQ_VENV_PYTHON = Path("/usr/local/share/pynq-venv/bin/python3")
FPGA_MANAGER_FW = Path("/sys/class/fpga_manager/fpga0/firmware")
FPGA_MANAGER_STATE = Path("/sys/class/fpga_manager/fpga0/state")
FIRMWARE_DIR = Path("/lib/firmware")


def find_pynq_python() -> str:
    if PYNQ_VENV_PYTHON.exists():
        return str(PYNQ_VENV_PYTHON)
    return sys.executable or "python3"


def ensure_root_if_needed(skip_overlay: bool, no_sudo: bool) -> None:
    if skip_overlay or no_sudo or os.name == "nt" or os.geteuid() == 0:
        return
    python_bin = find_pynq_python()
    print("[INFO] Root gerekli, sudo ile yeniden baslatiliyor...")
    print("[INFO] Sifre: xilinx")
    os.execvp("sudo", ["sudo", python_bin] + sys.argv)


def resolve_bin_file(bitfile: Path) -> Path:
    bitfile = bitfile.resolve()
    candidates = [
        bitfile.with_suffix(".bin"),
        bitfile.parent / f"{bitfile.name}.bin",
        bitfile if bitfile.suffix == ".bin" else None,
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    raise FileNotFoundError(
        "gps_uart_pmod.bin yok. Jupyter'dan gps_uart_pmod.bin dosyasini yukleyin.\n"
        f"  Aranan: {bitfile.with_suffix('.bin')}"
    )


def load_overlay_sysfs(bitfile: Path) -> None:
    binfile = resolve_bin_file(bitfile)
    if not FPGA_MANAGER_FW.exists():
        raise RuntimeError("fpga_manager yok")

    state = FPGA_MANAGER_STATE.read_text().strip() if FPGA_MANAGER_STATE.exists() else ""
    if state == "operating":
        print("[INFO] FPGA zaten operating durumda, bitstream atlanabilir.")
        return

    FIRMWARE_DIR.mkdir(parents=True, exist_ok=True)
    fw_name = "gps_uart.bin"
    target = FIRMWARE_DIR / fw_name
    shutil.copy2(binfile, target)

    print(f"[INFO] fpga_manager: {binfile.name} -> {target}")
    FPGA_MANAGER_FW.write_text(fw_name)

    deadline = time.time() + 30.0
    last_state = ""
    while time.time() < deadline:
        state = FPGA_MANAGER_STATE.read_text().strip()
        if state != last_state:
            print(f"[INFO] fpga_manager state: {state}")
            last_state = state
        if state == "operating":
            print("[OK] Bitstream yuklendi.")
            return
        if state in {"unknown", "error"}:
            break
        time.sleep(0.2)

    raise RuntimeError(f"Bitstream yuklenemedi (state={last_state})")


def fpga_state() -> str:
    if FPGA_MANAGER_STATE.exists():
        return FPGA_MANAGER_STATE.read_text().strip()
    return ""


def ensure_fpga_operating() -> None:
    state = fpga_state()
    if state == "operating":
        print(f"[OK] FPGA state: {state}")
        return
    raise RuntimeError(
        f"FPGA bitstream yuklu degil (state={state!r}).\n"
        "  Bus error almamak icin once bitstream yukleyin:\n"
        "    cd /home/xilinx/jupyter_notebooks\n"
        "    sudo cp gps_uart_pmod.bin /lib/firmware/gps_uart.bin\n"
        "    echo gps_uart.bin | sudo tee /sys/class/fpga_manager/fpga0/firmware\n"
        "    cat /sys/class/fpga_manager/fpga0/state\n"
        "  'operating' gorunmeden GPS scripti calistirmayin."
    )


class MmioUart:
    RX = 0x00
    TX = 0x04
    SR = 0x08
    CR = 0x0C

    SR_RX_VALID = 0x01
    SR_TX_EMPTY = 0x04

    def __init__(self, base: int = UART_BASE_ADDR, size: int = UART_MAP_SIZE) -> None:
        self._fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        self._map = mmap.mmap(
            self._fd,
            size,
            mmap.MAP_SHARED,
            mmap.PROT_READ | mmap.PROT_WRITE,
            offset=base,
        )

    def close(self) -> None:
        self._map.close()
        os.close(self._fd)

    def _read32(self, offset: int) -> int:
        self._map.seek(offset)
        return struct.unpack("<I", self._map.read(4))[0]

    def _write32(self, offset: int, value: int) -> None:
        self._map.seek(offset)
        self._map.write(struct.pack("<I", value & 0xFFFFFFFF))

    def status(self) -> int:
        return self._read32(self.SR)

    def dump_registers(self) -> None:
        sr = self._read32(self.SR)
        cr = self._read32(self.CR)
        rx_txt = "-"
        if sr & self.SR_RX_VALID:
            rx_txt = f"0x{self._read32(self.RX) & 0xFF:02X}"
        print(
            f"  UART @ 0x{UART_BASE_ADDR:08X}: "
            f"SR=0x{sr:04X} CR=0x{cr:04X} RX={rx_txt} | "
            f"RX_valid={bool(sr & self.SR_RX_VALID)} TX_empty={bool(sr & self.SR_TX_EMPTY)}"
        )

    def write_byte(self, value: int, timeout: float = 0.5) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.status() & self.SR_TX_EMPTY:
                self._write32(self.TX, value & 0xFF)
                return True
            time.sleep(0.001)
        return False

    def read_byte(self) -> Optional[int]:
        if self.status() & self.SR_RX_VALID:
            return self._read32(self.RX) & 0xFF
        return None


def probe_uart(uart: MmioUart, seconds: float = 10.0) -> None:
    print("=== UART PROBE (sadece okuma) ===")
    print(f"FPGA state: {fpga_state()}")
    print(f"Adres: 0x{UART_BASE_ADDR:08X}")
    print("GPS bagliysa TX -> Pin 10 (RPi) veya PMOD A Pin 2 olmali.\n")

    total = 0
    deadline = time.time() + seconds
    last_report = time.time()
    while time.time() < deadline:
        value = uart.read_byte()
        if value is not None:
            total += 1
            ch = chr(value) if 32 <= value < 127 else "."
            print(f"[RX] byte={value:3d} (0x{value:02X}) '{ch}'")
        if time.time() - last_report >= 2.0:
            uart.dump_registers()
            last_report = time.time()
        time.sleep(0.002)

    print(f"\n[SONUC] {seconds:.0f} sn icinde {total} byte alindi.")
    uart.dump_registers()


def loopback_test(uart: MmioUart, rounds: int = 20) -> None:
    print("=== LOOPBACK TEST (FPGA UART gonder/al) ===")
    print("GPS modulunu CIKAR.")
    print("RPi: Pin 8 (TXD) ile Pin 10 (RXD) arasina JUMPER.")
    print("PMOD A: Pin 1 ile Pin 2 arasina JUMPER.")
    print("Sonra Enter'a bas...")
    try:
        input()
    except EOFError:
        pass

    ok = 0
    for i in range(rounds):
        byte_out = 0x55 + (i % 10)
        if not uart.write_byte(byte_out):
            print(f"[TX] {i}: gonderilemedi (TX FIFO dolu)")
            continue
        time.sleep(0.01)
        byte_in = None
        for _ in range(50):
            byte_in = uart.read_byte()
            if byte_in is not None:
                break
            time.sleep(0.002)
        if byte_in == byte_out:
            ok += 1
            print(f"[OK] {i}: gonderildi=0x{byte_out:02X} alindi=0x{byte_in:02X}")
        else:
            got = "yok" if byte_in is None else f"0x{byte_in:02X}"
            print(f"[FAIL] {i}: gonderildi=0x{byte_out:02X} alindi={got}")

    uart.dump_registers()
    print(f"\n[SONUC] {ok}/{rounds} loopback OK")
    if ok >= rounds // 2:
        print("FPGA UART calisiyor -> sorun GPS kablosunda veya GPS modulunde.")
    else:
        print("FPGA UART calismiyor -> bitstream/pin tasarimi sorunu olabilir.")


def send_test_pattern(uart: MmioUart, text: str = "PYNQ_UART_TEST\n") -> None:
    print("=== TX TEST (sadece gonderme) ===")
    sent = 0
    for ch in text:
        if uart.write_byte(ord(ch)):
            sent += 1
        time.sleep(0.01)
    uart.dump_registers()
    print(f"[SONUC] {sent}/{len(text)} byte gonderildi.")
    print("Osiloskop veya loopback jumper ile Pin 8 cikisini kontrol edebilirsin.")


def test_uart(uart: MmioUart, seconds: float = 8.0) -> int:
    print(f"[TEST] {seconds:.0f} sn GPS verisi dinleniyor...")
    count = 0
    sample = bytearray()
    deadline = time.time() + seconds
    while time.time() < deadline:
        value = uart.read_byte()
        if value is not None:
            count += 1
            if len(sample) < 120:
                sample.append(value)
        else:
            time.sleep(0.005)

    sr = uart.status()
    preview = sample.decode("ascii", errors="replace")
    print(f"[TEST] {count} byte alindi, SR=0x{sr:04X}")
    if preview:
        print(f"[TEST] Ornek: {preview[:80]!r}")
    else:
        print("[TEST] Hic veri yok!")
        print("       Kablo kontrol:")
        print("         GPS TX -> PYNQ Pin 10")
        print("         GPS RX -> PYNQ Pin 8")
        print("         VCC    -> Pin 1 (3.3V)")
        print("         GND    -> Pin 6")
    return count


def read_line_devmem(uart: MmioUart, timeout: float = 1.0) -> str:
    buf = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = uart.read_byte()
        if value is not None:
            buf += bytes([value])
            if value == ord("\n"):
                return buf.decode("ascii", errors="ignore").strip()
        else:
            time.sleep(0.005)
    return ""


def dm_to_decimal(value: str, direction: str, degree_digits: int) -> Optional[float]:
    if not value or not direction:
        return None
    try:
        degrees = float(value[:degree_digits])
        minutes = float(value[degree_digits:])
        decimal = degrees + minutes / 60.0
        if direction in ("S", "W"):
            decimal = -decimal
        return decimal
    except ValueError:
        return None


def parse_coordinates(sentence: str) -> Optional[Tuple[float, float]]:
    if not sentence.startswith("$"):
        return None
    parts = sentence.strip().split(",")
    if len(parts) < 6:
        return None
    header = parts[0]
    if "GGA" in header:
        if len(parts) < 10 or parts[6] in ("0", ""):
            return None
        lat = dm_to_decimal(parts[2], parts[3], 2)
        lon = dm_to_decimal(parts[4], parts[5], 3)
    elif "RMC" in header:
        if len(parts) < 10 or parts[2] != "A":
            return None
        lat = dm_to_decimal(parts[3], parts[4], 2)
        lon = dm_to_decimal(parts[5], parts[6], 3)
    else:
        return None
    if lat is None or lon is None:
        return None
    return lat, lon


def format_coordinate(value: Optional[float]) -> str:
    return "-" if value is None else f"{value:.6f} derece"


def read_gps_devmem(uart: MmioUart, verbose: bool = True) -> None:
    print(f"[INFO] GPS okuma basladi (/dev/mem @ 0x{UART_BASE_ADDR:08X})")
    print("[INFO] Pencere kenari / acik hava. Ctrl+C ile cik.\n")

    idle = 0
    while True:
        line = read_line_devmem(uart, timeout=1.0)
        if not line:
            idle += 1
            if verbose and idle % 15 == 0:
                sr = uart.status()
                print(f"[BEKLE] Veri yok ({idle} sn)... SR=0x{sr:04X} | GPS LED yanıyor mu?")
            continue
        idle = 0
        if not line.startswith("$"):
            if verbose:
                print(f"[RAW] {line}")
            continue
        coords = parse_coordinates(line)
        if coords is None:
            if verbose:
                print(f"[NMEA] {line}")
            continue
        lat, lon = coords
        print(f"Enlem : {format_coordinate(lat)}")
        print(f"Boylam: {format_coordinate(lon)}")
        print("-" * 32)


def main() -> None:
    parser = argparse.ArgumentParser(description="NEO-6M GPS (PYNQ-Z2)")
    parser.add_argument("--overlay", default=DEFAULT_OVERLAY)
    parser.add_argument("--skip-overlay", action="store_true")
    parser.add_argument("--no-sudo", action="store_true")
    parser.add_argument("--test-only", action="store_true", help="8 sn test, cik")
    parser.add_argument("--probe", action="store_true", help="10 sn ham byte + register izle")
    parser.add_argument("--loopback", action="store_true", help="Pin8-Pin10 jumper ile gonder/al testi")
    parser.add_argument("--tx-test", action="store_true", help="Sadece TX gonder")
    args = parser.parse_args()

    ensure_root_if_needed(args.skip_overlay, args.no_sudo)

    if not args.skip_overlay:
        load_overlay_sysfs(Path(args.overlay))

    ensure_fpga_operating()
    uart = MmioUart()
    try:
        if args.loopback:
            loopback_test(uart)
            return
        if args.tx_test:
            send_test_pattern(uart)
            return
        if args.probe:
            probe_uart(uart)
            return

        count = test_uart(uart, seconds=8.0 if args.test_only else 5.0)
        if args.test_only:
            return
        if count == 0:
            print("\n[UYARI] GPS'ten byte gelmedi. Kablo/pin kontrol et, sonra tekrar dene.\n")
        read_gps_devmem(uart)
    finally:
        uart.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Durduruldu.")
    except Exception as exc:
        print(f"[HATA] {exc}", file=sys.stderr)
        sys.exit(1)
