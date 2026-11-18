#!/bin/sh

set -eu

# Shard 1 owns shared checks; every shard still tests the installed Docker package.
# No argument keeps the complete local validation contract.
case "${1:-all}" in
  all|pytest) scope="${1:-all}" ;;
  *) echo "Unknown CI check scope: $1" >&2; exit 2 ;;
esac

if [ "$scope" = all ]; then
  python scripts/validate_release.py
  ruff check .
  mypy src/autonavlog
fi
python -m pytest -p scripts.pytest_shard --cov=autonavlog --cov-report=term-missing --durations=30
if [ "$scope" = all ]; then
  python scripts/validate_performance_data.py data/performance
  python scripts/validate_runtime_data.py data
  python scripts/export_schemas.py --check
  python -m build
fi
