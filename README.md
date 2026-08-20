# Fusion v15 subscription liveness repro

A Fusion gateway pinned to **HotChocolate 15.1.17** never notices when a subgraph stops
delivering a subscription without closing the connection. The gateway waits on
`MoveNextAsync` forever: no exception, no close frame, no log line. A client on a
WebSocket keeps receiving its own protocol pings and believes the subscription is healthy.

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

`SIGSTOP` leaves the process and its TCP connection alive, so nothing is closed. This is
the same condition as a pod frozen, or killed without a graceful shutdown — and notably
**TCP keepalive does not detect it**, because the kernel keeps acknowledging while the
process is stopped.

Resume with `kill -CONT <pid>`.

### Expected (the defect)

The probe goes silent and stays silent. No error frame, no `event: complete`, no
exception anywhere. The gateway holds the subscription open indefinitely.

### What to watch

Whether SSE keepalive comments (`:`) keep arriving during the freeze. They are emitted by
`EventStreamResultFormatter.KeepAliveJob` — a 12s timer that writes `:\n\n` when the stream
has been quiet for 8s — and the gateway's SSE reader consumes them without surfacing them
as events.

That distinction is the whole design constraint for a fix: an idle healthy stream still
carries **bytes** but produces no **events**. So a read deadline must sit on the response
stream, not around the deserialized event sequence — at the event layer, idle and dead are
identical and any timeout would kill working subscriptions.

## Note on v16

`ChilliCream/fusion-demo` will not reproduce this. It pins HotChocolate 16.6.0-p.8 and its
gateway uses `AddNatsEventStreamBroker`, so subscription events reach the gateway through
NATS JetStream rather than a per-subscriber SSE stream. The transport at fault here is not
in play there.

## Verified output

Run on HotChocolate 15.1.17 via `python3 repro.py`:

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

Data stops at the freeze. No error frame, no `event: complete`, no exception — 90 seconds later
the subscription is still open and still silent.

**The keepalives are the point.** They are emitted by the *gateway's* own response formatter to
its client, on a 12s timer, and they keep arriving while the gateway receives nothing from the
frozen subgraph. Keepalives are per-hop: each SSE producer runs its own timer, so bytes arriving
on the downstream hop say nothing about upstream health.

That is the same illusion a WebSocket client hits one layer up — the gateway keeps sending
protocol pings from a healthy pod while the subscription behind it is dead. A client watching
heartbeats cannot distinguish a working subscription from a broken one.

## Environment gotchas

Two things unrelated to the defect that will otherwise waste your time:

- **Use `localhost`, not `127.0.0.1`.** Under a network-restricted sandbox the gateway's outbound
  connection to a literal loopback IP fails with `SocketException (13): Permission denied`, which
  surfaces as an immediately-closed SSE stream. Both `UseUrls` and `subgraph-config.json` use
  `localhost` here.
- **`DOTNET_hostBuilder__reloadConfigOnChange=false`** (set by the run scripts). The default
  `appsettings.json` file-watcher recurses until the stack overflows on tmpfs and container
  overlay filesystems, killing the process inside `WebApplication.CreateBuilder` before it logs
  anything.
