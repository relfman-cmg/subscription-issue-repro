#!/usr/bin/env bash
# Confirms the subgraph is frozen and the gateway is not.
#
# A frozen process keeps its listening socket, so "is the port open" proves nothing. What
# distinguishes frozen from healthy is that the TCP connection still completes while the
# application never answers — which is exactly the production condition being reproduced.
set -uo pipefail

SUBGRAPH_PORT=${SUBGRAPH_PORT:-5311}
GATEWAY_PORT=${GATEWAY_PORT:-5310}

pid_on() { lsof -t -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | head -1; }

# macOS STAT: T = stopped (SIGSTOP), S/R = running, prefix + means foreground
state() {
  local pid=$1
  [ -z "$pid" ] && { echo "no process"; return; }
  local stat
  stat=$(ps -o stat= -p "$pid" 2>/dev/null | tr -d ' ')
  case "$stat" in
    "")     echo "unknown (ps unavailable)" ;;
    T*|*T*) echo "STOPPED  (stat=$stat)" ;;
    *)      echo "running  (stat=$stat)" ;;
  esac
}

# Does the app answer, as opposed to merely accepting the connection?
answers() {
  local port=$1
  if curl -s -m 4 -o /dev/null -X POST "http://127.0.0.1:${port}/graphql" \
       -H 'Content-Type: application/json' -d '{"query":"{__typename}"}' 2>/dev/null; then
    echo "answers HTTP"
  else
    echo "NO RESPONSE within 4s"
  fi
}

sub_pid=$(pid_on "$SUBGRAPH_PORT")
gw_pid=$(pid_on "$GATEWAY_PORT")

printf 'subgraph  :%s  pid=%-7s %s | %s\n' "$SUBGRAPH_PORT" "${sub_pid:--}" "$(state "$sub_pid")" "$(answers "$SUBGRAPH_PORT")"
printf 'gateway   :%s  pid=%-7s %s | %s\n' "$GATEWAY_PORT"  "${gw_pid:--}"  "$(state "$gw_pid")"  "$(answers "$GATEWAY_PORT")"
echo
echo "Correct state for the repro:"
echo "  subgraph  STOPPED   + NO RESPONSE   <- frozen, socket still open"
echo "  gateway   running   + answers HTTP  <- alive, still sending pings to the client"
