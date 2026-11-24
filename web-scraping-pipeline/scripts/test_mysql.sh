#!/usr/bin/env bash
# Run every test against a throwaway MySQL server, then delete it. Needs mysqld.
set -euo pipefail
cd "$(dirname "$0")/.."
BIN="${MYSQL_BIN:-}"
[ -z "$BIN" ] || PATH="$BIN:$PATH"
PORT="${MYSQL_TEST_PORT:-33306}"
DIR="$(mktemp -d /tmp/harvest-mysql.XXXXXX)"
PID=""
cleanup() {
  if [ -n "$PID" ]; then kill "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true; fi
  rm -rf "$DIR"
}
trap cleanup EXIT
mysqld --no-defaults --initialize-insecure --datadir="$DIR/data" --log-error="$DIR/init.log"
mysqld --no-defaults --datadir="$DIR/data" --port="$PORT" --bind-address=127.0.0.1 \
  --socket="$DIR/s.sock" --mysqlx=OFF --log-error="$DIR/server.log" &
PID=$!
for _ in $(seq 60); do
  mysqladmin --no-defaults -uroot --socket="$DIR/s.sock" ping >/dev/null 2>&1 && break
  sleep 0.5
done
mysql --no-defaults -uroot --socket="$DIR/s.sock" -e "CREATE DATABASE harvest"
export HARVEST_MYSQL_URL="mysql://root@127.0.0.1:$PORT/harvest" HARVEST_REQUIRE_MYSQL=1
if [ "$#" -gt 0 ]; then "$@"; else "${PYTHON:-python3}" -m pytest -q; fi
