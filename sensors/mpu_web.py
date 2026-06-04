#!/usr/bin/env python3
"""
PYNQ-Z2 + MPU6050 canli web panosu (AXI GPIO bit-bang I2C).

Kartta calistir (i2c_gpio overlay zaten 'operating' olmali):
  sudo python3 mpu_web.py

Tarayicidan ac:
  http://192.168.2.99:8080

Gosterir: ivme (g), jiroskop (deg/s), sicaklik, gerceklesen pitch/roll,
canli cizgi grafikler ve 3D egim gostergesi.
"""

import argparse
import json
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from axi_gpio_i2c import AxiGpioI2C

# MPU6050 register
PWR_MGMT_1   = 0x6B
SMPLRT_DIV   = 0x19
CONFIG       = 0x1A
GYRO_CONFIG  = 0x1B
ACCEL_CONFIG = 0x1C
ACCEL_XOUT_H = 0x3B
WHO_AM_I     = 0x75
ACCEL_SCALE  = 16384.0
GYRO_SCALE   = 131.0

state_lock = threading.Lock()
state = {
    "ax": 0.0, "ay": 0.0, "az": 0.0,
    "gx": 0.0, "gy": 0.0, "gz": 0.0,
    "temp": 0.0,
    "pitch": 0.0, "roll": 0.0,
    "who": 0,
    "samples": 0,
    "ok": False,
    "err": "",
    "mono_at_update": 0.0,
}


def s16(high, low):
    val = (high << 8) | low
    return val - 65536 if val >= 0x8000 else val


def init_mpu(bus, addr):
    bus.write_byte_data(addr, PWR_MGMT_1, 0x00)
    time.sleep(0.1)
    bus.write_byte_data(addr, SMPLRT_DIV, 0x07)
    bus.write_byte_data(addr, CONFIG, 0x00)
    bus.write_byte_data(addr, GYRO_CONFIG, 0x00)
    bus.write_byte_data(addr, ACCEL_CONFIG, 0x00)


def reader_thread(base, addr):
    bus = AxiGpioI2C(base=base)
    try:
        who = bus.read_byte_data(addr, WHO_AM_I)
        init_mpu(bus, addr)
        with state_lock:
            state["who"] = who
            state["ok"] = True
        count = 0
        while True:
            try:
                d = bus.read_i2c_block_data(addr, ACCEL_XOUT_H, 14)
                ax = s16(d[0], d[1]) / ACCEL_SCALE
                ay = s16(d[2], d[3]) / ACCEL_SCALE
                az = s16(d[4], d[5]) / ACCEL_SCALE
                temp = s16(d[6], d[7]) / 340.0 + 36.53
                gx = s16(d[8], d[9]) / GYRO_SCALE
                gy = s16(d[10], d[11]) / GYRO_SCALE
                gz = s16(d[12], d[13]) / GYRO_SCALE
                pitch = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))
                roll = math.degrees(math.atan2(ay, az))
                count += 1
                with state_lock:
                    state.update(ax=ax, ay=ay, az=az, gx=gx, gy=gy, gz=gz,
                                 temp=temp, pitch=pitch, roll=roll,
                                 samples=count, err="",
                                 mono_at_update=time.monotonic())
            except Exception as e:
                with state_lock:
                    state["err"] = str(e)
            time.sleep(0.05)
    finally:
        bus.close()


HTML_PAGE = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PYNQ MPU6050</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font-family:'Segoe UI',system-ui,sans-serif; background:#0d1117; color:#e6edf3; }
  header { padding:14px 20px; background:#161b22; border-bottom:1px solid #30363d;
           display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
  header h1 { font-size:18px; margin:0; font-weight:600; }
  .badge { padding:4px 12px; border-radius:20px; font-size:13px; font-weight:600; }
  .ok { background:#1a7f37; color:#fff; } .bad { background:#9e6a03; color:#fff; }
  .hint { font-size:12px; color:#8b949e; }
  .wrap { display:grid; grid-template-columns:340px 1fr; gap:0; min-height:calc(100vh - 55px); }
  @media (max-width:880px){ .wrap{ grid-template-columns:1fr; } }
  .panel { padding:18px; overflow-y:auto; border-right:1px solid #30363d; }
  .card { background:#161b22; border:1px solid #30363d; border-radius:10px; padding:14px; margin-bottom:14px; }
  .card h2 { font-size:12px; text-transform:uppercase; letter-spacing:.5px; color:#8b949e; margin:0 0 10px; }
  .row { display:flex; justify-content:space-between; padding:4px 0; font-size:14px; }
  .row span:first-child{ color:#8b949e; }
  .mono { font-variant-numeric:tabular-nums; }
  .big { font-size:24px; font-weight:700; }
  .charts { padding:18px; display:flex; flex-direction:column; gap:14px; }
  canvas.chart { width:100%; height:200px; background:#161b22; border:1px solid #30363d; border-radius:10px; }
  .cube-wrap { display:flex; align-items:center; justify-content:center; padding:20px;
               perspective:600px; background:#161b22; border:1px solid #30363d; border-radius:10px; }
  .cube { width:120px; height:120px; position:relative; transform-style:preserve-3d; transition:transform .08s linear; }
  .face { position:absolute; width:120px; height:120px; border:2px solid #2ea043;
          background:rgba(46,160,67,.18); display:flex; align-items:center; justify-content:center;
          font-size:13px; color:#7ee787; font-weight:600; }
  .f-front{ transform:translateZ(60px);} .f-back{ transform:rotateY(180deg) translateZ(60px);}
  .f-right{ transform:rotateY(90deg) translateZ(60px);} .f-left{ transform:rotateY(-90deg) translateZ(60px);}
  .f-top{ transform:rotateX(90deg) translateZ(60px); background:rgba(88,166,255,.25); border-color:#388bfd; color:#79c0ff;}
  .f-bottom{ transform:rotateX(-90deg) translateZ(60px);}
</style>
</head>
<body>
<header>
  <h1>PYNQ-Z2 · MPU6050 (AXI GPIO I2C)</h1>
  <span id="badge" class="badge bad">WAITING</span>
  <span class="hint" id="updated"></span>
</header>
<div class="wrap">
  <div class="panel">
    <div class="card">
      <h2>Acceleration (g)</h2>
      <div class="row"><span>X</span><b id="ax" class="mono big">-</b></div>
      <div class="row"><span>Y</span><b id="ay" class="mono big">-</b></div>
      <div class="row"><span>Z</span><b id="az" class="mono big">-</b></div>
    </div>
    <div class="card">
      <h2>Gyroscope (°/s)</h2>
      <div class="row"><span>X</span><b id="gx" class="mono">-</b></div>
      <div class="row"><span>Y</span><b id="gy" class="mono">-</b></div>
      <div class="row"><span>Z</span><b id="gz" class="mono">-</b></div>
    </div>
    <div class="card">
      <h2>Orientation / Temperature</h2>
      <div class="row"><span>Pitch</span><b id="pitch" class="mono">-</b></div>
      <div class="row"><span>Roll</span><b id="roll" class="mono">-</b></div>
      <div class="row"><span>Temperature</span><b id="temp" class="mono">-</b></div>
    </div>
    <div class="card">
      <h2>Status</h2>
      <div class="row"><span>WHO_AM_I</span><b id="who" class="mono">-</b></div>
      <div class="row"><span>Samples</span><b id="samples" class="mono">0</b></div>
      <div class="row"><span>Error</span><b id="err" class="mono" style="font-size:11px">-</b></div>
    </div>
  </div>
  <div class="charts">
    <div class="cube-wrap">
      <div class="cube" id="cube">
        <div class="face f-front">FRONT</div><div class="face f-back">BACK</div>
        <div class="face f-right">RIGHT</div><div class="face f-left">LEFT</div>
        <div class="face f-top">TOP</div><div class="face f-bottom">BOTTOM</div>
      </div>
    </div>
    <canvas class="chart" id="accChart"></canvas>
    <canvas class="chart" id="gyroChart"></canvas>
  </div>
</div>
<script>
const N=120;
const acc={x:[],y:[],z:[]}, gyro={x:[],y:[],z:[]};
function push(arr,v){ arr.push(v); if(arr.length>N) arr.shift(); }
function drawChart(id,series,colors,range){
  const c=document.getElementById(id), ctx=c.getContext('2d');
  const w=c.width=c.clientWidth, h=c.height=c.clientHeight;
  ctx.clearRect(0,0,w,h);
  ctx.strokeStyle='#30363d'; ctx.lineWidth=1;
  ctx.beginPath(); ctx.moveTo(0,h/2); ctx.lineTo(w,h/2); ctx.stroke();
  series.forEach((arr,si)=>{
    ctx.strokeStyle=colors[si]; ctx.lineWidth=2; ctx.beginPath();
    arr.forEach((v,i)=>{
      const x=i/(N-1)*w;
      const y=h/2 - (v/range)*(h/2-8);
      i?ctx.lineTo(x,y):ctx.moveTo(x,y);
    });
    ctx.stroke();
  });
}
async function tick(){
  try{
    const d=await (await fetch('/data',{cache:'no-store'})).json();
    const b=document.getElementById('badge');
    const ago=d.seconds_ago!=null?d.seconds_ago:9999;
    if(d.ok && ago<2){ b.textContent='LIVE'; b.className='badge ok'; }
    else { b.textContent='WAITING'; b.className='badge bad'; }
    const f=(v,n=2)=>v!=null?v.toFixed(n):'-';
    ax.textContent=f(d.ax); ay.textContent=f(d.ay); az.textContent=f(d.az);
    gx.textContent=f(d.gx,1); gy.textContent=f(d.gy,1); gz.textContent=f(d.gz,1);
    pitch.textContent=f(d.pitch,1)+'°'; roll.textContent=f(d.roll,1)+'°';
    temp.textContent=f(d.temp,1)+' °C';
    who.textContent='0x'+(d.who||0).toString(16).toUpperCase();
    samples.textContent=d.samples; err.textContent=d.err||'-';
    updated.textContent=ago<2?'live data':('last update '+Math.round(ago)+'s ago');
    document.getElementById('cube').style.transform=
      `rotateX(${(-d.pitch)||0}deg) rotateY(${(d.roll)||0}deg)`;
    push(acc.x,d.ax);push(acc.y,d.ay);push(acc.z,d.az);
    push(gyro.x,d.gx);push(gyro.y,d.gy);push(gyro.z,d.gz);
    drawChart('accChart',[acc.x,acc.y,acc.z],['#f85149','#3fb950','#58a6ff'],2);
    drawChart('gyroChart',[gyro.x,gyro.y,gyro.z],['#f85149','#3fb950','#58a6ff'],250);
  }catch(e){}
}
setInterval(tick,100); tick();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
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
    ap = argparse.ArgumentParser(description="PYNQ MPU6050 web panosu")
    ap.add_argument("--base", type=lambda x: int(x, 0), default=0x41200000)
    ap.add_argument("--addr", type=lambda x: int(x, 0), default=0x68)
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    t = threading.Thread(target=reader_thread, args=(args.base, args.addr), daemon=True)
    t.start()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"[OK] MPU6050 panosu hazir: http://<KART_IP>:{args.port}")
    print(f"     Ornek: http://192.168.2.99:{args.port}")
    print("     Ctrl+C ile cik.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Kapatiliyor.")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
