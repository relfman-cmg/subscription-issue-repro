#!/usr/bin/env python3
"""Drives the whole repro: starts both services, subscribes, freezes the subgraph, watches.

    python3 repro.py

On vanilla HotChocolate 15.1.17 the subscription goes silent when the subgraph is frozen
and never produces an error frame, a completion, or an exception.
"""
import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
FREEZE_AFTER = int(os.environ.get("FREEZE_AFTER", "16"))
WATCH_AFTER = int(os.environ.get("WATCH_AFTER", "90"))
QUERY = "subscription Probe { onTick { number at } }"

# See run-subgraph.sh: the config file-watcher can recurse until the stack overflows.
ENV = dict(os.environ, DOTNET_hostBuilder__reloadConfigOnChange="false")


def wait_port(port, timeout=45):
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = socket.socket()
        s.settimeout(1)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except Exception:
            time.sleep(1)
        finally:
            s.close()
    return False


def port_free(port):
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("localhost", port))
        return False   # something is already listening
    except Exception:
        return True
    finally:
        s.close()


def main():
    # A leftover process holding the port makes wait_port() succeed against the wrong server, so
    # the freeze targets a pid that is not serving and the run silently reports no defect.
    for port in (5310, 5311):
        if not port_free(port):
            sys.exit(f"port {port} is already in use — kill the stale process first:\n"
                     f"  kill -TERM $(lsof -t -nP -iTCP:{port} -sTCP:LISTEN)")
    procs = {}
    start = time.time()
    stamp = lambda: f"+{time.time() - start:6.1f}s"
    try:
        for name, port, d in (("subgraph", 5311, "Subgraph"), ("gateway", 5310, "Gateway")):
            procs[name] = subprocess.Popen(
                ["dotnet", f"{d}.dll"], cwd=f"{ROOT}/{d}/bin/Debug/net10.0",
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=ENV)
            if not wait_port(port):
                sys.exit(f"{name} never listened on {port}")
            print(f"{stamp()} {name} up on {port} (pid {procs[name].pid})")

        conn = http.client.HTTPConnection("127.0.0.1", 5310, timeout=WATCH_AFTER + 60)
        conn.request("POST", "/graphql", body=json.dumps({"query": QUERY}).encode(),
                     headers={"Accept": "text/event-stream", "Content-Type": "application/json"})
        resp = conn.getresponse()
        print(f"{stamp()} subscribed: HTTP {resp.status} {resp.getheader('Content-Type')}")
        if resp.status != 200:
            print(resp.read(800).decode(errors="replace"))
            return

        frozen_at = None
        data = keepalives = 0
        last = time.time()
        freeze_at = time.time() + FREEZE_AFTER

        while True:
            if frozen_at is None and time.time() >= freeze_at:
                os.kill(procs["subgraph"].pid, signal.SIGSTOP)
                frozen_at = time.time()
                print(f"{stamp()} *** SIGSTOP subgraph — process and TCP connection left alive ***")
            if frozen_at and time.time() - frozen_at > WATCH_AFTER:
                print(f"{stamp()} watched {WATCH_AFTER}s after freeze")
                break
            line = resp.readline()
            if not line:
                print(f"{stamp()} STREAM CLOSED by server")
                break
            text = line.decode(errors="replace").rstrip("\r\n")
            if not text:
                continue
            gap, last = time.time() - last, time.time()
            if text.startswith(":"):
                keepalives += 1
                print(f"{stamp()} keepalive                (gap {gap:5.1f}s)")
            else:
                if text.startswith("data:"):
                    data += 1
                print(f"{stamp()} {text[:100]}  (gap {gap:5.1f}s)")

        print(f"\nRESULT  data frames={data}  keepalives={keepalives}")
        print("Silence with no error frame and no close is the defect.")
    finally:
        for p in procs.values():
            try:
                os.kill(p.pid, signal.SIGCONT)
            except Exception:
                pass
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        print("cleaned up")


if __name__ == "__main__":
    main()
