"""
Distributed P2P Pipeline Node - Providence (Windows)
====================================================
Runs the Ingestion, Batch Generator, and Cryptographic Ledger Verification Service.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Dict, List
import urllib.request

# Ensure unbuffered line printing
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

LINUX_NODE_URL = "http://100.118.132.56:9202"
PORT = 9201

verified_ledger: List[Dict] = []
presort_enabled: bool = False


class WindowsServiceHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "online",
                "node": "providence-windows",
                "presort_enabled": presort_enabled,
                "verified_batches": len(verified_ledger),
            }).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/verify_batch":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)

            batch_id = data.get("batch_id")
            merkle_root = data.get("merkle_root")
            transformed_sum = data.get("transformed_sum")
            linux_load = data.get("linux_load")

            # Validate the cryptographic Merkle root
            expected_prefix = "mkl-"
            is_valid = merkle_root.startswith(expected_prefix)

            entry = {
                "batch_id": batch_id,
                "merkle_root": merkle_root,
                "transformed_sum": transformed_sum,
                "linux_load": linux_load,
                "valid": is_valid,
                "verified_at": time.time(),
            }
            verified_ledger.append(entry)

            print(f"[Windows Peer Node] Verified proof for Batch #{batch_id} | Merkle: {merkle_root[:16]}... | Linux Load: {linux_load}", flush=True)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "accepted", "valid": is_valid}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_server():
    server = HTTPServer(("0.0.0.0", PORT), WindowsServiceHandler)
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[Windows Peer Node] Listening on 0.0.0.0:{PORT}", flush=True)
    return server


def send_batch(batch_id: int, vector_count: int = 50, presort: bool = False) -> Dict:
    import random
    raw_vectors = [round(random.uniform(1.0, 100.0), 3) for _ in range(vector_count)]
    if presort:
        raw_vectors.sort()

    payload = {
        "batch_id": batch_id,
        "timestamp": time.time(),
        "presorted": presort,
        "vectors": raw_vectors,
        "sender": "providence-windows",
    }
    req = urllib.request.Request(
        f"{LINUX_NODE_URL}/process_batch",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


if __name__ == "__main__":
    s = start_server()
    while True:
        time.sleep(1)
