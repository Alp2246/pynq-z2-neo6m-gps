#!/usr/bin/env python3
"""
PYNQ-Z2 + NEO-6M canli GPS web panosu.

Kartta calistir (bitstream zaten 'operating' olmali):
  sudo python3 gps_web.py --skip-overlay

Sonra PC tarayicidan ac:
  http://192.168.2.99:8080

Gosterir: enlem/boylam, fix durumu, uydu sayisi, uydu sinyal (SNR) cubuklari, harita.
Harita karolari tarayicinin internetinden gelir (PC internete bagliysa calisir).
"""

import argparse
import json
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
    "satellites": [],   # [{prn, elev, azim, snr}]
    "time_utc": "",
    "last_update": 0,
    "mono_at_update": 0.0,
    "raw_count": 0,
    "last_sentence": "",
}


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


# GSV mesajlari birden fazla cumleye bolunur; topla.
_gsv_accum = {}


def parse_sentence(line):
    if not line.startswith("$") or not _checksum_ok(line):
        return
    parts = line.strip().split("*")[0].split(",")
    head = parts[0]
    talker = head[3:] if len(head) >= 6 else head

    with state_lock:
        state["last_sentence"] = line.strip()

    if talker == "GGA" and len(parts) >= 10:
        with state_lock:
            state["time_utc"] = parts[1]
            state["quality"] = int(parts[6]) if parts[6].isdigit() else 0
            state["sats_used"] = int(parts[7]) if parts[7].isdigit() else 0
            lat = _dm_to_decimal(parts[2], parts[3], 2)
            lon = _dm_to_decimal(parts[4], parts[5], 3)
            if lat is not None and lon is not None:
                state["lat"], state["lon"] = lat, lon
            try:
                state["alt"] = float(parts[9]) if parts[9] else None
            except ValueError:
                pass
            state["fix"] = state["quality"] > 0
            state["last_update"] = time.time()
            state["mono_at_update"] = time.monotonic()

    elif talker == "RMC" and len(parts) >= 7:
        with state_lock:
            state["time_utc"] = parts[1]
            active = parts[2] == "A"
            lat = _dm_to_decimal(parts[3], parts[4], 2)
            lon = _dm_to_decimal(parts[5], parts[6], 3)
            if active and lat is not None and lon is not None:
                state["lat"], state["lon"] = lat, lon
                state["fix"] = True
            state["last_update"] = time.time()
            state["mono_at_update"] = time.monotonic()

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
            with state_lock:
                state["satellites"] = sorted(
                    _gsv_accum.get(talker, []),
                    key=lambda s: s["snr"], reverse=True,
                )


def reader_thread(uart):
    buf = bytearray()
    count = 0
    while True:
        value = uart.read_byte()
        # AXI UART'a asiri sik erisim 'external abort' verebiliyor;
        # her dongude kucuk bekleme koy (9600 baud = ~1 byte/ms).
        time.sleep(0.0005)
        if value is None:
            time.sleep(0.002)
            continue
        count += 1
        if value == 0x0A:  # \n
            try:
                line = buf.decode("ascii", errors="ignore").strip()
            except Exception:
                line = ""
            buf.clear()
            if line:
                parse_sentence(line)
            with state_lock:
                state["raw_count"] = count
        elif value != 0x0D:
            buf.append(value)
            if len(buf) > 200:
                buf.clear()


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
  .big { font-size:26px; font-weight:700; font-variant-numeric:tabular-nums; }
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
</style>
</head>
<body>
<header>
  <h1>PYNQ-Z2 · NEO-6M GPS</h1>
  <span id="fixBadge" class="badge fix-no">FIX YOK</span>
  <span class="hint" id="updated"></span>
</header>
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
<script>
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
  }catch(e){ /* ignore */ }
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
    ap.add_argument("--overlay", default="gps_uart.bit")
    ap.add_argument("--skip-overlay", action="store_true")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    if not args.skip_overlay:
        load_overlay_sysfs(Path(args.overlay))
    ensure_fpga_operating()

    uart = MmioUart()

    # HTTP sunucusunu arka planda calistir; UART okumayi ANA thread'de yap
    # (ana thread'de MMIO okuma kararli oldugu test edildi).
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()

    print(f"[OK] GPS panosu hazir: http://<KART_IP>:{args.port}")
    print(f"     Ornek: http://192.168.2.99:{args.port}")
    print("     Ctrl+C ile cik.")
    try:
        reader_thread(uart)  # ana thread'de sonsuz okuma dongusu
    except KeyboardInterrupt:
        print("\n[INFO] Kapatiliyor.")
    finally:
        server.shutdown()
        uart.close()


if __name__ == "__main__":
    main()
