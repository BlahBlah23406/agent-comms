"""
Distributed P2P Pipeline Node - code-47 (Ubuntu Linux)
======================================================
Runs the High-Throughput Numerical Transformation & Merkle Reduction Service.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Dict, List
import urllib.request

# Ensure unbuffered line printing
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

WINDOWS_NODE_URL = "http://100.74.182.18:9201"
PORT = 9202

processed_count: int = 0


class LinuxServiceHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "online",
                "node": "code47-linux",
                "processed_count": processed_count,
            }).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        global processed_count
        if self.path == "/process_batch":
            start_t = time.time()
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)

            batch_id = data.get("batch_id")
            vectors = data.get("vectors", [])
            presorted = data.get("presorted", False)

            # Perform high-performance numerical transformation
            transformed = [math.sin(v) * math.sqrt(v) for v in vectors]
            transformed_sum = round(sum(transformed), 4)

            # Compute Cryptographic Merkle Root Proof
            h = hashlib.sha256()
            for val in transformed:
                h.update(f"{val:.6f}".encode("ascii"))
            merkle_root = f"mkl-{h.hexdigest()}"

            compute_latency_ms = round((time.time() - start_t) * 1000, 3)
            processed_count += 1

            # Harvest Linux kernel load
            with open("/proc/loadavg", "r") as f:
                linux_load = float(f.read().strip().split()[0])

            print(f"[Linux Peer Node] Processed Batch #{batch_id} ({len(vectors)} vectors) | Latency: {compute_latency_ms}ms | Presorted: {presorted}", flush=True)

            # As a symmetric peer, directly push proof back to Windows verification node
            verify_payload = {
                "batch_id": batch_id,
                "merkle_root": merkle_root,
                "transformed_sum": transformed_sum,
                "linux_load": linux_load,
                "compute_time_ms": compute_latency_ms,
            }
            try:
                req = urllib.request.Request(
                    f"{WINDOWS_NODE_URL}/verify_batch",
                    data=json.dumps(verify_payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    pass
            except Exception as ex:
                print(f"[Linux Peer Node] Warning sending verification to Windows: {ex}", flush=True)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "processed",
                "batch_id": batch_id,
                "merkle_root": merkle_root,
                "compute_time_ms": compute_latency_ms,
            }).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_server():
    server = HTTPServer(("0.0.0.0", PORT), LinuxServiceHandler)
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[Linux Peer Node] Listening on 0.0.0.0:{PORT}", flush=True)
    return server


if __name__ == "__main__":
    s = start_server()
    while True:
        time.sleep(1)
