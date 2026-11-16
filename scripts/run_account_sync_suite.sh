#!/bin/sh
# Each invocation runs inside its own Firestore emulator and runner.
set -eu

case "${1:-}" in
  chromium|ipad-webkit|iphone-webkit)
    if [ "$#" = 1 ]; then
      npm --prefix web run test:sync -- --project="$1" --workers=2
    else
      case "$2" in 1/2|2/2) ;; *) echo "Invalid sync shard: $2" >&2; exit 2 ;; esac
      # One worker per isolated runner: tests never compete for its emulator or CPU.
      npm --prefix web run test:sync -- --project="$1" --fully-parallel --workers=1 --shard="$2"
    fi
    ;;
  contracts)
    npm --prefix web run test:firestore
    npm --prefix web run test:storage-upgrade
    npm --prefix web run test:migration
    ;;
  *)
    echo "Unknown account-sync suite: ${1:-missing}" >&2
    exit 2
    ;;
esac
