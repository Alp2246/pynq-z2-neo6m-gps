#!/usr/bin/env python3
"""
Ublox NEO-6M GPS modulunden NMEA verisi okur (Windows).

Kullanim:
  python neo_gps.py
  python neo_gps.py --port COM5

GPS modulu USB-UART adaptore bagliysa Aygit Yoneticisi'nden COM port numarasini
bulun. Modul dogrudan PYNQ PMOD A'ya bagliysa, Windows'tan okumak icin araya
USB-UART dongle (FTDI/CH340) takmaniz gerekir.
"""

import argparse
import importlib.util
import subprocess
import sys
import time
from typing import List, Optional, Tuple

BAUD_RATE = 9600
PROBE_TIMEOUT = 2.0


def ensure_package(import_name: str, pip_name: Optional[str] = None) -> None:
    """Paket kurulu degilse pip ile kur."""
    pip_name = pip_name or import_name
    if importlib.util.find_spec(import_name) is not None:
        print(f"[OK] {pip_name} zaten kurulu.")
        return

    print(f"[INFO] {pip_name} bulunamadi, kuruluyor...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name])
    print(f"[OK] {pip_name} kuruldu.")


def list_com_ports() -> List[str]:
    import serial.tools.list_ports

    ports = [p.device for p in serial.tools.list_ports.comports()]
    if not ports:
        return []

    print("[INFO] Bulunan COM portlari:")
    for info in serial.tools.list_ports.comports():
        desc = info.description or "Bilinmeyen cihaz"
        print(f"  - {info.device}: {desc}")
    return ports


def looks_like_nmea(port: str) -> bool:
    """Porttan kisa sure NMEA akisi gelip gelmedigini kontrol et."""
    import serial

    try:
        with serial.Serial(
            port=port,
            baudrate=BAUD_RATE,
            timeout=0.5,
        ) as ser:
            deadline = time.time() + PROBE_TIMEOUT
            while time.time() < deadline:
                raw = ser.readline()
                if raw and raw.startswith(b"$"):
                    return True
    except (serial.SerialException, OSError):
        return False

    return False


def find_serial_port(preferred: Optional[str] = None) -> str:
    """COM portunu bul; tercih edilen port verilmisse onu kullan."""
    import serial.tools.list_ports

    if preferred:
        available = {p.device for p in serial.tools.list_ports.comports()}
        if preferred.upper() not in {p.upper() for p in available}:
            raise FileNotFoundError(
                f"{preferred} bulunamadi. GPS modulunun USB kablosunun takili "
                "oldugundan emin olun."
            )
        for p in available:
            if p.upper() == preferred.upper():
                return p
        return preferred

    ports = list_com_ports()
    if not ports:
        raise FileNotFoundError(
            "Hic COM portu bulunamadi. GPS modulunu USB ile baglayin ve "
            "Aygit Yoneticisi > Baglanti noktalari (COM ve LPT) bolumunu kontrol edin."
        )

    if len(ports) == 1:
        print(f"[INFO] Tek port bulundu: {ports[0]}")
        return ports[0]

    print("[INFO] GPS verisi gonderen port araniyor...")
    for port in ports:
        if looks_like_nmea(port):
            print(f"[OK] GPS verisi bulundu: {port}")
            return port

    print(f"[UYARI] NMEA verisi tespit edilemedi, ilk port kullaniliyor: {ports[0]}")
    print("[INFO] Yanlis portsa: python neo_gps.py --port COMx")
    return ports[0]


def format_coordinate(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value:.6f} derece"


def parse_coordinates(sentence: str) -> Optional[Tuple[float, float]]:
    """NMEA cumlesinden enlem/boylam dondur."""
    import pynmea2

    try:
        msg = pynmea2.parse(sentence, check=False)
    except pynmea2.ParseError:
        return None

    msg_type = getattr(msg, "sentence_type", "")
    if msg_type not in ("GGA", "RMC"):
        return None

    if msg_type == "RMC" and getattr(msg, "status", "") != "A":
        return None

    if msg_type == "GGA" and str(getattr(msg, "gps_qual", "0")) in ("0", ""):
        return None

    latitude = getattr(msg, "latitude", None)
    longitude = getattr(msg, "longitude", None)
    if latitude is None or longitude is None:
        return None

    return latitude, longitude


def read_gps(port: str) -> None:
    import serial

    print(f"\n[INFO] {port} uzerinden {BAUD_RATE} baud ile okuma basliyor...")
    print("[INFO] Konum icin modulu acik havaya cikarin. Durdurmak icin Ctrl+C.\n")

    with serial.Serial(
        port=port,
        baudrate=BAUD_RATE,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=1.0,
    ) as ser:
        while True:
            raw = ser.readline()
            if not raw:
                continue

            line = raw.decode("ascii", errors="ignore").strip()
            if not line.startswith("$"):
                continue

            coords = parse_coordinates(line)
            if coords is None:
                continue

            lat, lon = coords
            print(f"Enlem : {format_coordinate(lat)}")
            print(f"Boylam: {format_coordinate(lon)}")
            print("-" * 32)


def main() -> None:
    parser = argparse.ArgumentParser(description="NEO-6M GPS okuyucu (Windows)")
    parser.add_argument(
        "--port",
        help="COM portu (ornegin COM5). Verilmezse otomatik aranir.",
    )
    args = parser.parse_args()

    ensure_package("pynmea2")
    ensure_package("serial", "pyserial")

    port = find_serial_port(args.port)
    read_gps(port)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Okuma durduruldu.")
    except Exception as exc:
        print(f"[HATA] {exc}", file=sys.stderr)
        sys.exit(1)
