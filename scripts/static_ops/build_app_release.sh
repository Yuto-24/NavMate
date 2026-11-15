#!/bin/sh
# Trusted container command, sent on stdin; candidate receives no provider credentials.
set -eu
phase() {
  result=0
  python /release_timing.py --file /release-metrics/build.json --phase "$@" || result=$?
  chown --no-dereference "$ARTIFACT_UID:$ARTIFACT_GID" /release-metrics/build.json
  return "$result"
}
git config --global --add safe.directory /app
# Install the candidate's wheel, not the newer tooling's dependency version.
# pip resolves the candidate's exact pyproject pin together with this wheel.
set -- vendor/jma_gpv_weather-*.whl
test "$#" -eq 1
test -f "$1"
phase dependencies-python python -m pip install 'setuptools>=69' wheel "$1" '.[msm,test]'
phase dependencies-node npm --prefix web ci
phase dependencies-browser npm --prefix web exec -- playwright install --with-deps chromium
phase source-validation python scripts/validate_release.py
phase source-validation python scripts/validate_performance_data.py data/performance
phase source-validation python scripts/validate_runtime_data.py data
phase source-validation python scripts/export_schemas.py --check
phase source-validation npm --prefix web run typecheck
phase static-build npm --prefix web run build:static
phase artifact-tests npm --prefix web run test:static-artifact
python -m http.server 4121 --bind 127.0.0.1 --directory web/dist-static > /tmp/static-server.log 2>&1 &
server_pid=$!
trap 'kill "$server_pid"' EXIT
curl --fail --retry 10 --retry-connrefused --retry-delay 1 http://127.0.0.1:4121/ >/dev/null
phase e2e npm --prefix web run test:static
# Only the hint directory/inventory need runner writes after the isolated build.
set -- web/dist-static/release.json web/dist-static/weather/msm
if [ -f web/dist-static/weather/msm/freshness.json ]; then
  set -- "$@" web/dist-static/weather/msm/freshness.json
fi
chown --no-dereference "$ARTIFACT_UID:$ARTIFACT_GID" "$@"
