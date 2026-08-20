# Fusion v15 subscription liveness repro

A Fusion gateway pinned to **HotChocolate 15.1.17** never notices when a subgraph stops
delivering a subscription without closing the connection. The gateway waits on
`MoveNextAsync` forever: no exception, no close frame, no log line.

Two projects, no database, no auth, no broker — so a hang can only be attributed to the
subgraph subscription transport.

| | |
|---|---|
| `Subgraph` | `subscription onTick` emitting every 5s, on `http://127.0.0.1:5311/graphql` |
| `Gateway` | Fusion gateway over that one subgraph, on `http://127.0.0.1:5310/graphql` |

## Setup

```bash
chmod +x *.sh
./compose.sh
```

Builds the subgraph, exports its SDL, runs `fusion subgraph pack` + `fusion compose` to
produce `gateway.fgp`, then builds the gateway.

## Reproduce

Three terminals.

```bash
./run-subgraph.sh          # terminal 1
./run-gateway.sh           # terminal 2
python3 probe.py 180       # terminal 3 — subscribes through the gateway
```

Ticks should appear every 5s. Then freeze the subgraph:

```bash
kill -STOP $(lsof -t -nP -iTCP:5311 -sTCP:LISTEN)
```

`SIGSTOP` leaves the process and its TCP connection alive, so nothing is closed — the same
condition as a pod frozen, or killed without a graceful shutdown. TCP keepalive does not
detect it: the kernel keeps acknowledging while the process is stopped. Resume with
`kill -CONT <pid>`.

`python3 repro.py` scripts the whole sequence; `python3 ws-probe.py` shows the same thing
over a WebSocket. `./check-frozen.sh` confirms the subgraph is frozen and the gateway is not.

## Result

```
+   2.3s subscribed: HTTP 200 text/event-stream; charset=utf-8
+   5.8s data: {"data":{"onTick":{"number":1,"at":"20:54:45"}}}
+  10.8s data: {"data":{"onTick":{"number":2,"at":"20:54:50"}}}
+  15.8s data: {"data":{"onTick":{"number":3,"at":"20:54:55"}}}
+  20.8s *** SIGSTOP subgraph — process and TCP connection left alive ***
+  20.8s data: {"data":{"onTick":{"number":4,"at":"20:55:00"}}}
+  38.3s keepalive                (gap  17.5s)
+  50.3s keepalive                (gap  12.0s)
+  62.3s keepalive                (gap  12.0s)
+  74.3s keepalive                (gap  12.0s)
+  86.3s keepalive                (gap  12.0s)
+  98.3s keepalive                (gap  12.0s)
+ 110.3s keepalive                (gap  12.0s)

RESULT  data frames=4  keepalives=7
```

Data stops at the freeze. No error frame, no `event: complete`, no exception — 90 seconds
later the subscription is still open and still silent.

**The keepalives are the point.** Those `:` comments come from the *gateway's* own
`EventStreamResultFormatter.KeepAliveJob` — a 12s timer that fires when its stream has been
quiet for 8s — so they keep arriving while the gateway receives nothing from the frozen
subgraph. Keepalives are per-hop: bytes on the downstream hop say nothing about upstream
health. A WebSocket client sees the same illusion one layer up, in protocol pings.

That also fixes the shape of any fix. The subgraph emits keepalives while healthy and idle,
but `HotChocolate.Transport.Http`'s SSE reader consumes them without yielding a result — so
an idle stream and a dead one are identical at the event layer and distinguishable only at
the byte layer. A read deadline must sit on the response stream; one around the event
sequence would kill working subscriptions.

## Note on v16

`ChilliCream/fusion-demo` will not reproduce this. It pins 16.6.0-p.8 and its gateway uses
`AddNatsEventStreamBroker`, so events reach it through NATS JetStream rather than a
per-subscriber SSE stream. The transport at fault here is not in play.

## Environment gotchas

Unrelated to the defect, but they will waste your time:

- **Use `localhost`, not `127.0.0.1`.** Under a network-restricted sandbox the gateway's
  outbound connection to a literal loopback IP fails with `SocketException (13): Permission
  denied`, surfacing as an immediately-closed SSE stream.
- **`DOTNET_hostBuilder__reloadConfigOnChange=false`** (set by the run scripts). The default
  `appsettings.json` file-watcher recurses until the stack overflows on tmpfs and container
  overlay filesystems, killing the process inside `WebApplication.CreateBuilder` before it
  logs anything.
