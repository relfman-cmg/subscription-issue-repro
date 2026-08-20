#!/usr/bin/env python3
"""Subscribes through the Fusion gateway and timestamps every SSE frame.

    python3 probe.py [seconds]

Then freeze the subgraph from another terminal:

    kill -STOP $(lsof -t -nP -iTCP:5311 -sTCP:LISTEN)

On 15.1.17 the output simply stops: no error frame, no completion, no exception. Lines
starting with ':' are keepalive comments -- watch whether they keep arriving during the
freeze, since that is what makes a read deadline safe rather than a false-positive machine.
"""
import http.client
import json
import sys
import time

SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 180
QUERY = "subscription Probe { onTick { number at } }"

conn = http.client.HTTPConnection("127.0.0.1", 5310, timeout=SECONDS + 30)
conn.request("POST", "/graphql", body=json.dumps({"query": QUERY}).encode(), headers={
    "Accept": "text/event-stream",
    "Content-Type": "application/json",
})
resp = conn.getresponse()
start = time.time()


def stamp():
    return f"+{time.time() - start:7.1f}s"


print(f"{stamp()} HTTP {resp.status} {resp.getheader('Content-Type')}")
if resp.status != 200:
    print(resp.read(1000).decode(errors="replace"))
    raise SystemExit(1)

print(f"{stamp()} subscribed — now freeze the subgraph:")
print("           kill -STOP $(lsof -t -nP -iTCP:5311 -sTCP:LISTEN)")

data_frames = keepalives = 0
last = start
try:
    while time.time() - start < SECONDS:
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
            print(f"{stamp()} keepalive              (gap {gap:5.1f}s)")
        elif text.startswith("data:"):
            data_frames += 1
            print(f"{stamp()} {text[:110]}  (gap {gap:5.1f}s)")
        else:
            print(f"{stamp()} {text[:110]}  (gap {gap:5.1f}s)")
except (TimeoutError, OSError) as exc:
    print(f"{stamp()} read stopped: {type(exc).__name__}: {exc}")

print()
print(f"RESULT after {time.time() - start:.0f}s: data frames={data_frames} keepalives={keepalives}")
print("Silence with no error frame and no close is the defect.")
