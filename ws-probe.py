#!/usr/bin/env python3
"""Subscribes over a WebSocket (graphql-transport-ws) — the transport Nitro uses.

    python3 ws-probe.py [seconds]

This is the client's-eye view of the customer complaint. Freeze the subgraph:

    kill -STOP $(lsof -t -nP -iTCP:5311 -sTCP:LISTEN)

'next' frames stop. 'ping' frames keep arriving, because the gateway generating them is
healthy. That is exactly what the customer saw and why they believed the subscription
was working.

Minimal hand-rolled WebSocket client: stdlib only, text frames, no extensions.
"""
import base64
import json
import os
import socket
import struct
import sys
import time

SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 180
QUERY = "subscription Probe { onTick { number at } }"
HOST, PORT = "127.0.0.1", 5310
# GET /graphql 301-redirects to /graphql/ because the Nitro tool owns that route.
PATH = os.environ.get("WS_PATH", "/graphql/ws")


def handshake(sock):
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((
        f"GET {PATH} HTTP/1.1\r\nHost: {HOST}:{PORT}\r\n"
        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
        "Sec-WebSocket-Protocol: graphql-transport-ws\r\n\r\n"
    ).encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise SystemExit("server closed during handshake")
        buf += chunk
    head = buf.split(b"\r\n\r\n")[0].decode(errors="replace")
    if "101" not in head.split("\r\n")[0]:
        raise SystemExit("upgrade refused:\n" + head)
    return head.split("\r\n")[0], buf.split(b"\r\n\r\n", 1)[1]


def send_text(sock, payload):
    data = json.dumps(payload).encode()
    header = bytearray([0x81])
    mask = os.urandom(4)
    n = len(data)
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126)
        header += struct.pack("!H", n)
    else:
        header.append(0x80 | 127)
        header += struct.pack("!Q", n)
    header += mask
    sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


class Reader:
    def __init__(self, sock, initial=b""):
        self.sock, self.buf = sock, initial

    def _need(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                return False
            self.buf += chunk
        return True

    def frame(self):
        if not self._need(2):
            return None
        b1, b2 = self.buf[0], self.buf[1]
        opcode, length, off = b1 & 0x0F, b2 & 0x7F, 2
        if length == 126:
            if not self._need(4):
                return None
            length = struct.unpack("!H", self.buf[2:4])[0]
            off = 4
        elif length == 127:
            if not self._need(10):
                return None
            length = struct.unpack("!Q", self.buf[2:10])[0]
            off = 10
        if not self._need(off + length):
            return None
        payload = self.buf[off:off + length]
        self.buf = self.buf[off + length:]
        return opcode, payload


def main():
    sock = socket.create_connection((HOST, PORT), timeout=SECONDS + 30)
    status, leftover = handshake(sock)
    start = time.time()
    print(f"+{0:6.1f}s {status}")
    reader = Reader(sock, leftover)

    send_text(sock, {"type": "connection_init", "payload": {}})
    counts = {}
    while time.time() - start < SECONDS:
        frame = reader.frame()
        if frame is None:
            print(f"+{time.time()-start:6.1f}s socket closed")
            break
        opcode, payload = frame
        stamp = f"+{time.time()-start:6.1f}s"
        if opcode == 0x8:
            print(f"{stamp} websocket CLOSE")
            break
        if opcode == 0x9:  # ws-level ping
            counts["ws-ping"] = counts.get("ws-ping", 0) + 1
            print(f"{stamp} websocket PING (transport keep-alive)")
            continue
        if opcode != 0x1:
            continue
        msg = json.loads(payload.decode(errors="replace"))
        kind = msg.get("type", "?")
        counts[kind] = counts.get(kind, 0) + 1
        if kind == "connection_ack":
            print(f"{stamp} connection_ack -> subscribing")
            send_text(sock, {"id": "1", "type": "subscribe", "payload": {"query": QUERY}})
        elif kind == "ping":
            send_text(sock, {"type": "pong"})
            print(f"{stamp} ping  (graphql-ws keep-alive; replied pong)")
        elif kind == "next":
            print(f"{stamp} next  {json.dumps(msg.get('payload'))[:90]}")
        else:
            print(f"{stamp} {kind}  {json.dumps(msg)[:120]}")

    print(f"\nRESULT {json.dumps(counts)}")
    print("Heartbeats without 'next' frames is the customer's exact experience.")


if __name__ == "__main__":
    main()
