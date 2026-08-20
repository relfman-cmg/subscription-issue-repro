# GitHub issue draft — ChilliCream/graphql-platform

Form: https://github.com/ChilliCream/graphql-platform/issues/new?template=bug_report.yml

---

**Product:** Hot Chocolate
**Version:** 15.1.17
**Link to minimal reproduction:** https://github.com/relfman-cmg/subscription-issue-repro

---

## Title

Fusion: a subgraph subscription that stalls without closing the connection is never detected — the gateway waits indefinitely

---

## Steps to reproduce

1. `chmod +x *.sh && ./compose.sh`
2. `./run-subgraph.sh` (terminal 1) — a subgraph whose `onTick` subscription emits nothing. This
   is the normal state for a subscription carrying occasional business events: idle nearly all
   the time.
3. `./run-gateway.sh` (terminal 2) — a Fusion gateway federating only that subgraph
4. Subscribe through the gateway with `subscription { onTick { number at } }`. We used Nitro at
   `http://127.0.0.1:5310/graphql`, which connects over `graphql-transport-ws`;
   `{"type":"connection_ack"}` comes back on the socket and the subscription sits open. SSE
   behaves the same way (`POST` the same endpoint with `Accept: text/event-stream`).
5. Freeze the subgraph, leaving its process and TCP connection alive:
   ```
   kill -STOP $(lsof -t -nP -iTCP:5311 -sTCP:LISTEN)
   ```
6. Wait. Nothing changes: no error, no completion, nothing in the gateway log, and `ping` frames
   keep arriving. The subscription is permanently dead and looks exactly as it did while healthy.

Repeating this with `TICK_SECONDS=5 ./run-subgraph.sh` shows the delivery side: `next` frames
arrive every 5s and stop the instant the subgraph is frozen, still with no error, no completion
and no log entry.

`SIGSTOP` reproduces the production condition exactly: the peer stops responding at the
application layer while the kernel keeps the socket open and keeps acknowledging. The same
state occurs when a pod is evicted or a node disappears — no FIN or RST reaches the gateway.

## What is expected?

The gateway detects that the subgraph stream has stopped delivering within some bounded
time and terminates the client subscription with an error, so the client can resubscribe.

## What is actually happening?

The gateway waits forever. There is no exception, no completion, no error frame and no log
entry. In Nitro the subscription stays open and `ping` frames keep arriving, so it looks
healthy while it will never deliver another event. On an idle subscription there is not even a
gap in delivery to notice: a healthy subscription and a permanently dead one are byte-for-byte
identical from the client's point of view. With events flowing the only signal is their
absence, which is indistinguishable from a quiet period.

## Relevant log output

```shell
(nothing — that is the defect)
```

## Additional context

### Mechanism

On the subgraph hop, a subscription is an SSE response: the gateway sends the request once
and thereafter only reads. `DefaultHttpGraphQLSubscriptionClient.SubscribeInternalAsync`
enumerates `response.ReadAsResultStreamAsync(...)` with no read deadline.

A pure reader cannot learn that its peer is gone. TCP only surfaces a dead peer on FIN, on
RST, or when the local side *sends* and retransmits to timeout. None occur here.
`SO_KEEPALIVE` is not set on the Fusion `HttpClient`, and setting it would not help: the
stopped process's kernel keeps acknowledging, so the probes are answered. The hop is
HTTP/1.1, so HTTP/2 pings do not apply either.

### The signal that does exist

The subgraph *does* keep writing to the stream while idle.
`EventStreamResultFormatter.KeepAliveJob` runs a 12s timer and emits an SSE comment
(`":\n\n"`) whenever the stream has been quiet for 8s. Those bytes stop the instant the
subgraph stalls.

They are invisible one layer up: `HotChocolate.Transport.Http`'s SSE reader recognises
keepalives (`IsKeepAlive`) and consumes them without yielding a result. So at the
deserialized-event layer an idle stream is indistinguishable from a dead one, while at the
byte layer the distinction is unambiguous.

### Suggested fix

An idle read deadline on the response stream — not on the event sequence. Because the
subgraph already emits keepalives roughly every 12s, a deadline comfortably above that
(e.g. 60s) distinguishes stalled from idle with no false positives. A timeout placed around
the event enumeration instead would kill healthy idle subscriptions.

We implemented this downstream as a `DelegatingHandler` on the Fusion `HttpClient` that
wraps `text/event-stream` response content in a stream enforcing a per-read deadline. It
detects the frozen-subgraph case in ~60s where previously it was never detected, and does
not fire on genuinely idle subscriptions. Happy to contribute it if the approach seems
right.

### Related

- #8976 — Fusion SSE subscription client missing `.WithCancellation()` (fixed)
- #8977 — Fusion gateway SSE subscriptions don't propagate cancellation to subgraphs (fixed)
- #10117 — subgraph *graceful* close surfaced as clean completion rather than an error

This report is the complementary case to #10117: there, the subgraph closes and the close is
mis-classified; here, the subgraph never closes at all and nothing is surfaced.

### Note on v16

`ChilliCream/fusion-demo` on 16.6.0-p.8 uses `AddNatsEventStreamBroker`, so subscription
events appear to reach the gateway through a broker rather than a per-subscriber SSE stream.
v16 may therefore be unaffected. Is a fix on the 15.x line in scope?

### Impact

This surfaced from a production incident in which one tenant received no subscription events
for over 14 hours after the subgraph pod was evicted. The client remained connected and was
receiving heartbeats throughout, and nothing server-side recorded a fault.
