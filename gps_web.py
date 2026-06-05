#!/usr/bin/env python3
"""
PYNQ-Z2 + NEO-6M canli GPS web panosu.

Kartta:
  sudo python3 gps_web.py
  veya: bash start_web.sh

Tarayici: http://192.168.2.99:8080
"""

import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from neo_gps_pynq import MmioUart, ensure_fpga_operating, load_overlay_sysfs

state_lock = threading.Lock()
state = {
    "fix": False,
    "quality": 0,
    "lat": None,
    "lon": None,
    "alt": None,
    "sats_used": 0,
    "satellites": [],
    "time_utc": "",
    "last_update": 0,
    "mono_at_update": 0.0,
    "raw_count": 0,
    "last_sentence": "",
    "nmea_decoded": {},
}

_gsv_accum = {}

_GGA_QUALITY = {
    0: "Fix yok",
    1: "GPS fix (SPS)",
    2: "DGPS fix",
    3: "PPS fix",
    4: "RTK sabit",
    5: "RTK float",
    6: "Tahmini",
    7: "Manuel",
    8: "Simulasyon",
}

_GSA_FIX = {1: "Fix yok", 2: "2D fix", 3: "3D fix"}

_NMEA_META = {
    "GGA": {
        "title": "$GPGGA — Fix Data (Konum Fix Verisi)",
        "about": (
            "GPS alıcısının o andaki konum fix bilgisini taşır. "
            "Enlem, boylam, yükseklik, kaç uydu kullanıldığı ve fix kalitesi burada yazar. "
            "Haritadaki konum ve fix göstergesi çoğunlukla bu mesajdan gelir."
        ),
    },
    "RMC": {
        "title": "$GPRMC — Recommended Minimum (Asgari Navigasyon)",
        "about": (
            "GPS modülünün gönderdiği asgari navigasyon paketidir. "
            "Konum, hız, yön ve tarih/saat tek cümlede gelir. "
            "A harfi fix var, V harfi fix yok anlamına gelir."
        ),
    },
    "GSA": {
        "title": "$GPGSA — Active Satellites (Aktif Uydular)",
        "about": (
            "Konum hesabında hangi uyduların kullanıldığını ve DOP değerlerini verir. "
            "PDOP/HDOP/VDOP düşükse konum daha güvenilirdir. "
            "Fix tipi 2D veya 3D olup olmadığını söyler."
        ),
    },
    "GSV": {
        "title": "$GPGSV — Satellites in View (Görünen Uydular)",
        "about": (
            "Gökyüzünde görülen uyduların listesidir. "
            "Her uydu için PRN numarası, elevasyon açısı, azimut ve sinyal gücü (SNR) yazar. "
            "Mesaj uzun olduğu için birkaç parçaya bölünerek gelir."
        ),
    },
    "VTG": {
        "title": "$GPVTG — Track Made Good (Yön ve Hız)",
        "about": (
            "Hareket yönünü (course) ve yer hızını verir. "
            "Deniz mili/saat (knot) ve km/saat olarak hız; derece cinsinden yön içerir."
        ),
    },
    "GLL": {
        "title": "$GPGLL — Geographic Position (Coğrafi Konum)",
        "about": (
            "Sadece enlem ve boylam ile fix geçerliliğini bildirir. "
            "GGA ve RMC'ye benzer ama daha kısadır; hız/tarih içermez."
        ),
    },
}

_RMC_RE = re.compile(
    r"^\$G[PN]RMC,([^,]*),([AV]),(\d+\.?\d*),([NS]),(\d+\.?\d*),([EW])"
)


def _dm_to_decimal(value, direction, deg_digits):
    if not value or not direction:
        return None
    try:
        degrees = float(value[:deg_digits])
        minutes = float(value[deg_digits:])
        dec = degrees + minutes / 60.0
        if direction in ("S", "W"):
            dec = -dec
        return dec
    except ValueError:
        return None


def _checksum_ok(sentence):
    if "*" not in sentence:
        return True
    body, _, cs = sentence[1:].partition("*")
    try:
        calc = 0
        for ch in body:
            calc ^= ord(ch)
        return calc == int(cs[:2], 16)
    except ValueError:
        return False


def _field(label, value, hint=""):
    return {"label": label, "value": value if value not in (None, "") else "—", "hint": hint}


def _store_nmea(talker, raw, fields):
    meta = _NMEA_META.get(talker, {"title": talker, "about": "NMEA mesajı"})
    with state_lock:
        state["nmea_decoded"][talker] = {
            "id": talker,
            "title": meta["title"],
            "about": meta.get("about", ""),
            "raw": raw,
            "fields": fields,
            "updated": time.time(),
        }


def _fmt_latlon_dm(value, direction, deg_digits):
    if not value or not direction:
        return "—"
    try:
        dec = _dm_to_decimal(value, direction, deg_digits)
        if dec is None:
            return f"{value} {direction}"
        return f"{abs(dec):.6f}° {'N' if dec >= 0 else 'S'}" if direction in ("N", "S") else f"{abs(dec):.6f}° {'E' if dec >= 0 else 'W'}"
    except ValueError:
        return f"{value} {direction}"


def decode_gga(parts, raw):
    q = int(parts[6]) if len(parts) > 6 and parts[6].isdigit() else 0
    fields = [
        _field("UTC saat", parts[1] if len(parts) > 1 else "",
               "Uydu saati, UTC olarak hhmmss.ss formatında. Örnek: 145023 = 14:50:23 UTC."),
        _field("Enlem", _fmt_latlon_dm(parts[2], parts[3] if len(parts) > 3 else "", 2),
               "Bulunduğun noktanın kuzey-güney konumu (WGS84). N=kuzey yarıküre, S=güney."),
        _field("Boylam", _fmt_latlon_dm(parts[4], parts[5] if len(parts) > 5 else "", 3),
               "Bulunduğun noktanın doğu-batı konumu (WGS84). E=doğu, W=batı."),
        _field("Fix kalitesi", _GGA_QUALITY.get(q, str(q)),
               "0 fix yok; 1 standart GPS; 2 diferansiyel GPS (DGPS). NEO-6M genelde 0 veya 1 gönderir."),
        _field("Kullanılan uydu sayısı", parts[7] if len(parts) > 7 else "",
               "Konum hesabına dahil edilen uydu sayısı. Çok olduğunda fix daha kararlı olur."),
        _field("HDOP", parts[8] if len(parts) > 8 else "",
               "Horizontal DOP — yatay konum hatası çarpanı. 1–2 iyi, 5 üstü zayıf geometri demektir."),
        _field("Rakım", f"{parts[9]} m" if len(parts) > 9 and parts[9] else "—",
               "Deniz seviyesine göre yükseklik (metre). Haritadaki rakım buradan gelir."),
        _field("Geoid ayrımı", f"{parts[11]} m" if len(parts) > 11 and parts[11] else "—",
               "WGS84 elipsoid ile gerçek deniz seviyesi arasındaki fark (metre)."),
    ]
    _store_nmea("GGA", raw, fields)


def decode_rmc(parts, raw):
    active = len(parts) > 2 and parts[2] == "A"
    fields = [
        _field("UTC saat", parts[1] if len(parts) > 1 else "",
               "O anki UTC saati (hhmmss.ss). Tarih alanı ayrıca gelir."),
        _field("Durum", "Geçerli (A)" if active else "Geçersiz (V)",
               "A = fix geçerli, konuma güvenilebilir. V = fix yok veya henüz kilitlenmedi."),
        _field("Enlem", _fmt_latlon_dm(parts[3], parts[4] if len(parts) > 4 else "", 2),
               "RMC içindeki enlem değeri; GGA ile birlikte çapraz kontrol için kullanılır."),
        _field("Boylam", _fmt_latlon_dm(parts[5], parts[6] if len(parts) > 6 else "", 3),
               "RMC içindeki boylam değeri."),
        _field("Hız", f"{parts[7]} knot" if len(parts) > 7 and parts[7] else "—",
               "Yer hızı, deniz mili/saat (knot). 1 knot ≈ 1.852 km/s."),
        _field("Yön (course)", f"{parts[8]}°" if len(parts) > 8 and parts[8] else "—",
               "Gerçek kuzeye göre hareket yönü, derece cinsinden (0–360)."),
        _field("Tarih", parts[9] if len(parts) > 9 else "",
               "UTC tarih, ddmmyy formatında. Örnek: 050626 = 5 Haziran 2026."),
        _field("Manyetik sapma", parts[10] if len(parts) > 10 else "",
               "Manyetik kuzey ile gerçek kuzey arası fark; boşsa gönderilmemiştir."),
    ]
    _store_nmea("RMC", raw, fields)


def decode_gsa(parts, raw):
    fix = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    prns = [p for p in parts[3:15] if p.isdigit()] if len(parts) > 15 else []
    fields = [
        _field("Mod", "Otomatik (A)" if len(parts) > 1 and parts[1] == "A" else "Manuel (M)",
               "A = alıcı 2D/3D modu otomatik seçer. M = kullanıcı zorlar (genelde A)."),
        _field("Fix tipi", _GSA_FIX.get(fix, str(fix)),
               "1 = fix yok; 2 = 2D (enlem/boylam); 3 = 3D (rakım da var)."),
        _field("Aktif PRN listesi", ", ".join(prns) if prns else "—",
               "Navigasyon çözümünde kullanılan GPS uydu numaraları (PRN 1–32)."),
        _field("PDOP", parts[15] if len(parts) > 15 else "",
               "Position DOP — 3B konum hatası çarpanı. Düşük değer daha iyi."),
        _field("HDOP", parts[16] if len(parts) > 16 else "",
               "Horizontal DOP — yatay (enlem/boylam) hata çarpanı."),
        _field("VDOP", parts[17] if len(parts) > 17 else "",
               "Vertical DOP — dikey (rakım) hata çarpanı."),
    ]
    _store_nmea("GSA", raw, fields)


def decode_gsv(parts, raw, sats_in_view):
    fields = [
        _field("Toplam parça sayısı", parts[1] if len(parts) > 1 else "",
               "GSV mesajı kaç NMEA cümlesine bölündü (genelde 2–4)."),
        _field("Bu parçanın numarası", parts[2] if len(parts) > 2 else "",
               "Şu an gelen parçanın sıra numarası."),
        _field("Görünen uydu sayısı", parts[3] if len(parts) > 3 else "",
               "Anten tarafından görülen toplam uydu sayısı."),
    ]
    for s in sats_in_view[:12]:
        fields.append(_field(
            f"Uydu PRN {s['prn']}",
            f"Elevasyon {s['elev']}° · Azimut {s['azim']}° · SNR {s['snr']} dB",
            f"PRN {s['prn']}: elevasyon=gökyüzündeki yükseklik açısı; "
            f"azimut=kuzeyden saat yönünde derece; SNR=sinyal gücü (yüksek=iyi).",
        ))
    _store_nmea("GSV", raw, fields)


def decode_vtg(parts, raw):
    fields = [
        _field("Yön (true north)", f"{parts[1]}°" if len(parts) > 1 and parts[1] else "—",
               "Gerçek (coğrafi) kuzeye göre hareket yönü, derece."),
        _field("Yön (magnetic)", f"{parts[3]}°" if len(parts) > 3 and parts[3] else "—",
               "Manyetik kuzeye göre yön; pusula ile karşılaştırma için."),
        _field("Hız (knot)", parts[5] if len(parts) > 5 else "—",
               "Yer hızı, deniz mili/saat."),
        _field("Hız (km/h)", parts[7] if len(parts) > 7 else "—",
               "Aynı hızın km/saat cinsinden değeri."),
        _field("Mod", parts[9] if len(parts) > 9 else "",
               "A = otonom GPS; D = diferansiyel; N = veri geçersiz."),
    ]
    _store_nmea("VTG", raw, fields)


def decode_gll(parts, raw):
    active = len(parts) > 6 and parts[6] == "A"
    fields = [
        _field("Enlem", _fmt_latlon_dm(parts[1], parts[2] if len(parts) > 2 else "", 2),
               "Coğrafi enlem; GGA/RMC ile aynı formatta."),
        _field("Boylam", _fmt_latlon_dm(parts[3], parts[4] if len(parts) > 4 else "", 3),
               "Coğrafi boylam."),
        _field("UTC saat", parts[5] if len(parts) > 5 else "",
               "Bu konum ölçümünün UTC saati."),
        _field("Durum", "Geçerli (A)" if active else "Geçersiz (V)",
               "A = fix geçerli; V = henüz güvenilir konum yok."),
    ]
    _store_nmea("GLL", raw, fields)


def _parse_rmc_parts(parts, line=None):
    active = len(parts) > 2 and parts[2] == "A"
    lat = lon = None
    if len(parts) >= 7 and parts[4] in ("N", "S") and parts[6] in ("E", "W"):
        lat = _dm_to_decimal(parts[3], parts[4], 2)
        lon = _dm_to_decimal(parts[5], parts[6], 3)
    elif line:
        m = _RMC_RE.match(line.split("*")[0])
        if m:
            active = m.group(2) == "A"
            lat = _dm_to_decimal(m.group(3), m.group(4), 2)
            lon = _dm_to_decimal(m.group(5), m.group(6), 3)
    return active, lat, lon


def parse_sentence(line):
    if not line.startswith("$"):
        return
    raw = line.strip()
    parts = raw.split("*")[0].split(",")
    head = parts[0]
    talker = head[3:] if len(head) >= 6 else head

    with state_lock:
        state["last_sentence"] = raw

    if talker == "GGA" and len(parts) >= 10:
        decode_gga(parts, raw)
        with state_lock:
            state["time_utc"] = parts[1]
            q = int(parts[6]) if parts[6].isdigit() else 0
            state["quality"] = q
            state["sats_used"] = int(parts[7]) if parts[7].isdigit() else 0
            if q > 0:
                lat = _dm_to_decimal(parts[2], parts[3], 2)
                lon = _dm_to_decimal(parts[4], parts[5], 3)
                if lat is not None and lon is not None:
                    state["lat"], state["lon"] = lat, lon
                try:
                    state["alt"] = float(parts[9]) if parts[9] else None
                except ValueError:
                    pass
                state["fix"] = True
                state["last_update"] = time.time()
                state["mono_at_update"] = time.monotonic()

    elif talker == "RMC" and len(parts) >= 3:
        decode_rmc(parts, raw)
        active, lat, lon = _parse_rmc_parts(parts, line)
        with state_lock:
            state["time_utc"] = parts[1] if len(parts) > 1 else state["time_utc"]
            if active and lat is not None and lon is not None:
                state["lat"], state["lon"] = lat, lon
                state["fix"] = True
            state["last_update"] = time.time()
            state["mono_at_update"] = time.monotonic()

    elif talker == "GSA" and len(parts) >= 18:
        decode_gsa(parts, raw)

    elif talker == "GSV" and len(parts) >= 4:
        try:
            total_msgs = int(parts[1])
            msg_num = int(parts[2])
        except ValueError:
            return
        sats = []
        i = 4
        while i + 3 < len(parts):
            prn = parts[i]
            elev = parts[i + 1]
            azim = parts[i + 2]
            snr = parts[i + 3]
            if prn:
                sats.append({
                    "prn": prn,
                    "elev": elev or "0",
                    "azim": azim or "0",
                    "snr": int(snr) if snr.isdigit() else 0,
                })
            i += 4
        if msg_num == 1:
            _gsv_accum[talker] = []
        _gsv_accum.setdefault(talker, []).extend(sats)
        if msg_num == total_msgs:
            merged = sorted(
                _gsv_accum.get(talker, []),
                key=lambda s: s["snr"], reverse=True,
            )
            decode_gsv(parts, raw, merged)
            with state_lock:
                state["satellites"] = merged

    elif talker == "VTG" and len(parts) >= 8:
        decode_vtg(parts, raw)

    elif talker == "GLL" and len(parts) >= 6:
        decode_gll(parts, raw)


def reader_thread(uart):
    buf = bytearray()
    count = 0
    while True:
        batch = 0
        while batch < 128:
            value = uart.read_byte()
            if value is None:
                break
            batch += 1
            count += 1
            if value == 0x0A:
                line = bytes(buf).decode("ascii", errors="ignore").strip()
                buf.clear()
                if line.startswith("$"):
                    parse_sentence(line)
                with state_lock:
                    state["raw_count"] = count
            elif value == 0x0D:
                pass
            elif value == ord("$"):
                buf.clear()
                buf.append(value)
            else:
                buf.append(value)
                if len(buf) > 120:
                    buf.clear()
        if batch == 0:
            time.sleep(0.003)


HTML_PAGE = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PYNQ NEO-6M GPS</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: 'Segoe UI', system-ui, sans-serif;
         background:#0d1117; color:#e6edf3; }
  header { padding:14px 20px; background:#161b22; border-bottom:1px solid #30363d;
           display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
  header h1 { font-size:18px; margin:0; font-weight:600; }
  .badge { padding:4px 12px; border-radius:20px; font-size:13px; font-weight:600; }
  .fix-yes { background:#1a7f37; color:#fff; }
  .fix-no  { background:#9e6a03; color:#fff; }
  .wrap { display:grid; grid-template-columns: 360px 1fr; gap:0; height:calc(100vh - 55px); }
  @media (max-width:820px){ .wrap{ grid-template-columns:1fr; height:auto; } #map{ height:50vh; } }
  .panel { padding:18px; overflow-y:auto; border-right:1px solid #30363d; }
  .card { background:#161b22; border:1px solid #30363d; border-radius:10px;
          padding:14px; margin-bottom:14px; }
  .card h2 { font-size:12px; text-transform:uppercase; letter-spacing:.5px;
             color:#8b949e; margin:0 0 10px; }
  .row { display:flex; justify-content:space-between; padding:4px 0; font-size:14px; }
  .row span:first-child { color:#8b949e; }
  .mono { font-variant-numeric:tabular-nums; }
  #map { width:100%; height:100%; }
  .sat { display:flex; align-items:center; gap:8px; margin:5px 0; font-size:12px; }
  .sat .prn { width:34px; color:#8b949e; }
  .bar-bg { flex:1; background:#21262d; border-radius:4px; height:14px; overflow:hidden; }
  .bar { height:100%; border-radius:4px; transition:width .3s; }
  .sat .val { width:42px; text-align:right; color:#8b949e; }
  .hint { font-size:12px; color:#8b949e; line-height:1.5; }
  .tabs { display:flex; gap:6px; margin-left:auto; }
  .tab { padding:6px 14px; border:1px solid #30363d; border-radius:8px;
         background:#21262d; color:#8b949e; cursor:pointer; font-size:13px; }
  .tab.active { background:#388bfd; color:#fff; border-color:#388bfd; }
  .view { display:none; height:calc(100vh - 55px); }
  .view.active { display:block; }
  .nmea-panel { padding:18px; overflow-y:auto; height:100%; max-width:720px; margin:0 auto; }
  .nmea-types { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
  .ntype { padding:8px 16px; border:1px solid #30363d; border-radius:8px;
           background:#21262d; color:#8b949e; cursor:pointer; font-size:14px; font-weight:600; }
  .ntype.active { background:#1f6feb; color:#fff; border-color:#1f6feb; }
  .ntype.missing { opacity:0.35; cursor:default; }
  .nmea-card { background:#161b22; border:1px solid #30363d; border-radius:10px; padding:18px; }
  .nmea-card h3 { margin:0 0 10px; font-size:16px; color:#58a6ff; line-height:1.4; }
  .nmea-card .about { font-size:14px; color:#c9d1d9; line-height:1.6; margin-bottom:14px;
                      padding:10px; background:#0d1117; border-radius:8px; border-left:3px solid #388bfd; }
  .nmea-card .raw { font-size:11px; color:#484f58; word-break:break-all; margin-bottom:16px;
                    font-family:Consolas,monospace; }
  .nmea-field { display:flex; gap:14px; padding:14px 0; border-bottom:1px solid #21262d; }
  .nmea-field:last-child { border-bottom:none; }
  .nmea-num { flex-shrink:0; width:28px; height:28px; border-radius:50%; background:#21262d;
              color:#58a6ff; font-weight:700; font-size:13px; display:flex; align-items:center;
              justify-content:center; margin-top:2px; }
  .nmea-lbl { font-size:12px; text-transform:uppercase; letter-spacing:.4px; color:#8b949e; margin-bottom:4px; }
  .nmea-val { font-size:18px; font-weight:700; font-variant-numeric:tabular-nums; margin-bottom:6px; }
  .nmea-desc { font-size:13px; color:#8b949e; line-height:1.55; }
</style>
</head>
<body>
<header>
  <h1>PYNQ-Z2 · NEO-6M GPS</h1>
  <span id="fixBadge" class="badge fix-no">FIX YOK</span>
  <span class="hint" id="updated"></span>
  <div class="tabs">
    <button class="tab active" data-view="pano">Pano</button>
    <button class="tab" data-view="nmea">NMEA</button>
  </div>
</header>
<div id="view-pano" class="view active">
<div class="wrap">
  <div class="panel">
    <div class="card">
      <h2>Konum</h2>
      <div class="row"><span>Enlem</span><b id="lat" class="mono">-</b></div>
      <div class="row"><span>Boylam</span><b id="lon" class="mono">-</b></div>
      <div class="row"><span>Rakim</span><b id="alt" class="mono">-</b></div>
      <div class="row"><span>UTC saat</span><b id="utc" class="mono">-</b></div>
    </div>
    <div class="card">
      <h2>Durum</h2>
      <div class="row"><span>Fix kalitesi</span><b id="qual" class="mono">0</b></div>
      <div class="row"><span>Kullanilan uydu</span><b id="used" class="mono">0</b></div>
      <div class="row"><span>Gorulen uydu</span><b id="seen" class="mono">0</b></div>
      <div class="row"><span>Alinan byte</span><b id="bytes" class="mono">0</b></div>
    </div>
    <div class="card">
      <h2>Uydu sinyalleri (SNR dB)</h2>
      <div id="sats"></div>
      <div class="hint" id="noSat">Uydu bekleniyor... Anteni acik gokyuzune dogrultun.</div>
    </div>
    <div class="card">
      <h2>Son NMEA</h2>
      <div class="hint mono" id="raw" style="word-break:break-all;">-</div>
    </div>
  </div>
  <div id="map"></div>
</div>
</div>
<div id="view-nmea" class="view">
  <div class="nmea-panel">
    <p class="hint" style="margin-top:0">Mesaj tipini seç — alanlar numaralı ve tek tek açıklanır.</p>
    <div id="nmeaTypes" class="nmea-types"></div>
    <div id="nmeaDetail"></div>
  </div>
</div>
<script>
const NMEA_ORDER = ['GGA','RMC','GSA','GSV','VTG','GLL'];
let activeNmea = 'GGA';
let lastNmeaDecoded = {};

document.getElementById('nmeaTypes').addEventListener('click', e=>{
  const btn = e.target.closest('.ntype');
  if(!btn || btn.classList.contains('missing')) return;
  activeNmea = btn.dataset.type;
  renderNmeaDetail(lastNmeaDecoded);
});

function renderNmeaTypes(dec){
  const box = document.getElementById('nmeaTypes');
  box.innerHTML = NMEA_ORDER.map(k=>{
    const ok = !!dec[k];
    const cls = 'ntype' + (k===activeNmea && ok ? ' active' : '') + (ok ? '' : ' missing');
    return `<button type="button" class="${cls}" data-type="${k}">${k}</button>`;
  }).join('');
  if(!dec[activeNmea]){
    const first = NMEA_ORDER.find(k=>dec[k]);
    if(first) activeNmea = first;
  }
}

function renderNmeaDetail(dec){
  renderNmeaTypes(dec);
  const detail = document.getElementById('nmeaDetail');
  const m = dec[activeNmea];
  if(!m){
    detail.innerHTML = '<p class="hint">Bu mesaj henüz gelmedi. GPS açıkken birkaç saniye bekle.</p>';
    return;
  }
  const flds = (m.fields||[]).map((f,i)=>`
    <div class="nmea-field">
      <div class="nmea-num">${i+1}</div>
      <div>
        <div class="nmea-lbl">${f.label}</div>
        <div class="nmea-val">${f.value}</div>
        <div class="nmea-desc">${f.hint||''}</div>
      </div>
    </div>`).join('');
  detail.innerHTML = `<div class="nmea-card">
    <h3>${m.title||activeNmea}</h3>
    <div class="about">${m.about||''}</div>
    <div class="raw">${m.raw||''}</div>
    ${flds}
  </div>`;
}
document.querySelectorAll('.tab').forEach(btn=>{
  btn.addEventListener('click',()=>{
    document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
    document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('view-'+btn.dataset.view).classList.add('active');
    if(btn.dataset.view==='pano' && map) setTimeout(()=>map.invalidateSize(),100);
  });
});
let map, marker, centered=false;
function initMap(){
  map = L.map('map').setView([39.0,35.0], 5);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    { maxZoom:19, attribution:'© OpenStreetMap' }).addTo(map);
}
function snrColor(v){
  if(v>=35) return '#2ea043';
  if(v>=25) return '#3fb950';
  if(v>=15) return '#d29922';
  if(v>0)   return '#bb8009';
  return '#484f58';
}
async function tick(){
  try{
    const r = await fetch('/data', {cache:'no-store'});
    const d = await r.json();
    const badge = document.getElementById('fixBadge');
    if(d.fix){ badge.textContent='FIX VAR'; badge.className='badge fix-yes'; }
    else { badge.textContent='FIX YOK'; badge.className='badge fix-no'; }
    document.getElementById('lat').textContent = d.lat!=null ? d.lat.toFixed(6)+'°' : '-';
    document.getElementById('lon').textContent = d.lon!=null ? d.lon.toFixed(6)+'°' : '-';
    document.getElementById('alt').textContent = d.alt!=null ? d.alt.toFixed(1)+' m' : '-';
    document.getElementById('utc').textContent = d.time_utc || '-';
    document.getElementById('qual').textContent = d.quality;
    document.getElementById('used').textContent = d.sats_used;
    document.getElementById('seen').textContent = d.satellites.length;
    document.getElementById('bytes').textContent = d.raw_count;
    document.getElementById('raw').textContent = d.last_sentence || '-';
    const box = document.getElementById('sats');
    const noSat = document.getElementById('noSat');
    box.innerHTML='';
    if(d.satellites.length){
      noSat.style.display='none';
      d.satellites.forEach(s=>{
        const row=document.createElement('div'); row.className='sat';
        const w=Math.min(100, s.snr*2);
        row.innerHTML=`<span class="prn">#${s.prn}</span>
          <span class="bar-bg"><span class="bar" style="width:${w}%;background:${snrColor(s.snr)}"></span></span>
          <span class="val">${s.snr||'-'}</span>`;
        box.appendChild(row);
      });
    } else { noSat.style.display='block'; }
    if(d.lat!=null && d.lon!=null){
      const ll=[d.lat,d.lon];
      if(!marker){ marker=L.marker(ll).addTo(map); }
      marker.setLatLng(ll);
      if(!centered){ map.setView(ll,16); centered=true; }
    }
    const ago = d.seconds_ago != null ? d.seconds_ago : 9999;
    if(ago < 3) document.getElementById('updated').textContent='canli veri';
    else document.getElementById('updated').textContent='son veri '+Math.round(ago)+' sn once';

    lastNmeaDecoded = d.nmea_decoded || {};
    renderNmeaDetail(lastNmeaDecoded);
  }catch(e){}
}
initMap();
setInterval(tick, 1000);
tick();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/data"):
            with state_lock:
                out = dict(state)
                out["nmea_decoded"] = dict(state["nmea_decoded"])
                mono = state.get("mono_at_update", 0.0)
                out["seconds_ago"] = max(0.0, time.monotonic() - mono) if mono else 9999.0
                payload = json.dumps(out).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


def main():
    ap = argparse.ArgumentParser(description="PYNQ NEO-6M GPS web panosu")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    overlay_bin = Path(__file__).resolve().parent / "gps_uart.bin"
    if not overlay_bin.exists():
        raise SystemExit(f"[HATA] {overlay_bin} yok")
    print("[1] gps_uart overlay yukleniyor...")
    load_overlay_sysfs(overlay_bin, force=True)
    ensure_fpga_operating()
    time.sleep(1.0)

    print("[2] UART aciliyor...")
    uart = MmioUart()
    uart.dump_registers()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()

    print(f"[OK] GPS panosu hazir: http://<KART_IP>:{args.port}")
    print(f"     Ornek: http://192.168.2.99:{args.port}")
    print("     Ctrl+C ile cik.")
    try:
        reader_thread(uart)
    except KeyboardInterrupt:
        print("\n[INFO] Kapatiliyor.")
    finally:
        server.shutdown()
        uart.close()


if __name__ == "__main__":
    main()
