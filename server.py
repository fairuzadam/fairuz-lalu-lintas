#!/usr/bin/env python3
"""
Server simulasi PLC lampu lalu lintas (persimpangan 4 arah).

Jalankan:  python3 server.py
  - Simulator : http://localhost:3000   (simulator.html)
  - HMI       : http://localhost:3001   (hmi.html)

Dua port itu berbagi satu "memori PLC" yang sama, jadi perintah dari HMI
langsung terlihat di simulator. Hanya pakai library bawaan Python.

Pemetaan I/O (gaya Mitsubishi):
  Input   X0 = START      X1 = STOP      X2 = EMERGENCY     X3 = MANUAL
  Output  Y0 = Utara-Selatan MERAH   Y1 = Utara-Selatan KUNING   Y2 = Utara-Selatan HIJAU
          Y3 = Timur-Barat   MERAH   Y4 = Timur-Barat   KUNING   Y5 = Timur-Barat   HIJAU
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
PAGES = {3000: "simulator.html", 3001: "hmi.html"}  # port -> halaman
SCAN = 0.1  # waktu scan PLC (detik)

# Urutan fase otomatis (satu siklus penuh)
ORDER = ["NS_GREEN", "NS_YELLOW", "ALL_RED_1", "EW_GREEN", "EW_YELLOW", "ALL_RED_2"]

#                   Y0 Y1 Y2 Y3 Y4 Y5
LAMPS = {
    "NS_GREEN":  [0, 0, 1, 1, 0, 0],
    "NS_YELLOW": [0, 1, 0, 1, 0, 0],
    "ALL_RED_1": [1, 0, 0, 1, 0, 0],
    "EW_GREEN":  [1, 0, 0, 0, 0, 1],
    "EW_YELLOW": [1, 0, 0, 0, 1, 0],
    "ALL_RED_2": [1, 0, 0, 1, 0, 0],
    "ALL_RED":   [1, 0, 0, 1, 0, 0],  # fase manual "semua merah"
}

lock = threading.Lock()
S = {
    "run": True,
    "mode": "AUTO",          # AUTO / MANUAL
    "emergency": False,      # True = kedip kuning
    "phase": "NS_GREEN",
    "remaining": 10.0,
    "times": {"green": 10, "yellow": 3, "allred": 1},
}


def duration(phase):
    t = S["times"]
    if phase.endswith("GREEN"):
        return t["green"]
    if phase.endswith("YELLOW"):
        return t["yellow"]
    return t["allred"]


def outputs():
    """Hitung Y0..Y5 dari kondisi sekarang (dipanggil saat lock dipegang)."""
    if S["emergency"]:
        on = 1 if (time.time() % 1.0) < 0.5 else 0  # kedip 1 Hz
        return [0, on, 0, 0, on, 0]
    if not S["run"]:
        return LAMPS["ALL_RED"]
    return LAMPS[S["phase"]]


def snapshot():
    with lock:
        return {
            "run": S["run"],
            "mode": S["mode"],
            "emergency": S["emergency"],
            "phase": S["phase"],
            "remaining": round(max(S["remaining"], 0), 1),
            "times": dict(S["times"]),
            "y": outputs(),
            "x": [int(S["run"]), int(not S["run"]), int(S["emergency"]), int(S["mode"] == "MANUAL")],
        }


def scan_loop():
    """Siklus scan PLC: timer fase jalan di sini."""
    last = time.time()
    while True:
        time.sleep(SCAN)
        now = time.time()
        dt, last = now - last, now
        with lock:
            if S["run"] and not S["emergency"] and S["mode"] == "AUTO":
                S["remaining"] -= dt
                if S["remaining"] <= 0:
                    nxt = ORDER[(ORDER.index(S["phase"]) + 1) % len(ORDER)]
                    S["phase"] = nxt
                    S["remaining"] = duration(nxt)


def apply_cmd(c):
    k = c.get("cmd")
    with lock:
        if k == "start":
            S["run"] = True
        elif k == "stop":
            S["run"] = False
        elif k == "emergency":
            S["emergency"] = bool(c.get("value"))
        elif k == "mode":
            if c.get("value") == "AUTO":
                S["mode"] = "AUTO"
                if S["phase"] not in ORDER:
                    S["phase"] = "ALL_RED_1"
                S["remaining"] = duration(S["phase"])
            else:
                S["mode"] = "MANUAL"
        elif k == "manual":
            p = c.get("value")
            if S["mode"] != "MANUAL":
                return {"ok": False, "msg": "Pindah ke mode MANUAL dulu"}
            if p not in ("NS_GREEN", "EW_GREEN", "ALL_RED"):
                return {"ok": False, "msg": "Fase tidak dikenal"}
            # Interlock: dua arah tidak boleh hijau bergantian tanpa semua merah
            cur = S["phase"]
            if (p == "NS_GREEN" and cur in ("EW_GREEN", "EW_YELLOW")) or (
                p == "EW_GREEN" and cur in ("NS_GREEN", "NS_YELLOW")
            ):
                return {"ok": False, "msg": "Interlock: lewat SEMUA MERAH dulu"}
            S["phase"] = p
            S["remaining"] = 0
        elif k == "times":
            for key in ("green", "yellow", "allred"):
                if key in c:
                    S["times"][key] = max(1, min(60, int(c[key])))
        elif k == "reset":
            S["phase"] = "NS_GREEN"
            S["remaining"] = duration("NS_GREEN")
            S["mode"] = "AUTO"
            S["emergency"] = False
            S["run"] = True
        else:
            return {"ok": False, "msg": "Perintah tidak dikenal"}
    return {"ok": True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/state":
            return self._send(200, snapshot())
        if path in ("/", "/index.html"):
            name = PAGES[self.server.server_address[1]]
        elif path.lstrip("/") in PAGES.values():
            name = path.lstrip("/")
        else:
            return self._send(404, {"error": "tidak ditemukan"})
        f = BASE / name
        if not f.exists():
            return self._send(404, {"error": name + " belum ada"})
        self._send(200, f.read_text(encoding="utf-8"), "text/html; charset=utf-8")

    def do_POST(self):
        if self.path.split("?")[0] != "/api/cmd":
            return self._send(404, {"error": "tidak ditemukan"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
            self._send(200, apply_cmd(data))
        except (ValueError, TypeError):
            self._send(400, {"ok": False, "msg": "Data tidak valid"})


def main():
    threading.Thread(target=scan_loop, daemon=True).start()
    for port, page in PAGES.items():
        srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print(f"{page:15s} -> http://localhost:{port}")
    print("Tekan Ctrl+C untuk berhenti.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nBerhenti.")


if __name__ == "__main__":
    main()
