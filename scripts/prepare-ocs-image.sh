#!/usr/bin/env bash
set -euo pipefail
umask 077

test "$(git -C reviewed rev-parse HEAD)" = "${SOURCE_SHA:?}"
test -z "$(git -C reviewed status --porcelain)"
image="pnec-backend:git-${SOURCE_SHA}-${IMAGE_ARCH:?}-r${GITHUB_RUN_ID:?}-a${GITHUB_RUN_ATTEMPT:?}"
docker build --pull --platform "linux/$IMAGE_ARCH" \
  --label "org.opencontainers.image.revision=$SOURCE_SHA" --tag "$image" reviewed
test "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image")" = "linux/$IMAGE_ARCH"

scratch=$(mktemp -d)
container="pnec-rehearsal-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"
cleanup() {
  if docker container inspect "$container" >/dev/null 2>&1; then
    docker logs --tail 40 "$container" >&2 || true
    docker rm -f "$container" >/dev/null || true
  fi
}
trap cleanup EXIT
mkdir "$scratch/data" "$scratch/data/uploads"
sudo chown 10001:10001 "$scratch/data" "$scratch/data/uploads"
secret=$(openssl rand -hex 32)
export SECRET_KEY="$secret"
runtime=(
  --network none --read-only --cap-drop ALL --security-opt no-new-privileges
  --init --memory 256m --memory-swap 256m --tmpfs /tmp:rw,mode=1777
  --mount "type=bind,src=$scratch/data,dst=/var/lib/pnec"
  -e SECRET_KEY -e DATABASE_URL=sqlite:////var/lib/pnec/synthetic.sqlite3
  -e FRONTEND_URL=https://powaynec.opencodingsociety.com
  -e PNEC_REVIEW_EPHEMERAL=false -e MAIL_DELIVERY=disabled
  -e UPLOAD_FOLDER=/var/lib/pnec/uploads -e SECURITY_STATE_PATH=/var/lib/pnec/limits.json
)

# Prepare disposable schema separately, then exercise the actual default entrypoint/CMD.
docker run --rm "${runtime[@]}" --entrypoint python "$image" -m flask --app main:app db upgrade

wait_healthy() {
  for ((attempt=0; attempt<60; attempt++)); do
    state=$(docker inspect --format '{{.State.Status}} {{.State.Health.Status}}' "$container")
    case "$state" in
      'running healthy') return ;;
      'running starting') sleep 2 ;;
      *) echo "Unexpected container state: $state" >&2; return 1 ;;
    esac
  done
  echo 'Timed out waiting for image health check' >&2
  return 1
}

start() {
  docker run -d --name "$container" "${runtime[@]}" "$image"
  wait_healthy
  docker exec "$container" sh -ec '
    test "$(id -u):$(id -g)" = 10001:10001
    test -w /var/lib/pnec/uploads && test -w /var/lib/pnec
    test ! -w /app
  '
  docker exec -i "$container" python - <<'PY'
from concurrent.futures import ThreadPoolExecutor
import json
from urllib.request import urlopen

def check(_):
    for route, expected in (
        ("health", {"status": "ok", "port": 8630}),
        ("ready", {"status": "ready", "schema_revision": "0002_announcements"}),
    ):
        with urlopen(f"http://127.0.0.1:8630/api/{route}", timeout=5) as response:
            body = json.load(response)
            assert all(body.get(key) == value for key, value in expected.items()), body

with ThreadPoolExecutor(max_workers=4) as pool:
    list(pool.map(check, range(24)))
PY
}

measure() {
  docker exec "$container" sh -ec '
    test "$(cat /sys/fs/cgroup/memory.max)" = 268435456
    test "$(cat /sys/fs/cgroup/memory.swap.max)" = 0
    awk '\''$1 == "oom" || $1 == "oom_kill" { if ($2 != 0) exit 1; seen++ }
         END { if (seen != 2) exit 1 }'\'' /sys/fs/cgroup/memory.events
    cat /sys/fs/cgroup/memory.peak
  '
}

start
docker exec -e PNEC_DOCKER_DISPOSABLE_TEST=true "$container" python scripts/check-docker-local.py
docker exec "$container" sh -ec 'printf synthetic > /var/lib/pnec/uploads/ci-marker'
peak_first=$(measure)
docker stop "$container" >/dev/null
docker rm "$container" >/dev/null
start
docker exec -i "$container" python - <<'PY'
from pathlib import Path
import sqlite3

assert Path("/var/lib/pnec/uploads/ci-marker").read_text() == "synthetic"
with sqlite3.connect("file:/var/lib/pnec/synthetic.sqlite3?mode=ro", uri=True) as db:
    assert db.execute("SELECT count(*) FROM users WHERE bio = ?",
                      ("Synthetic Docker check",)).fetchone() == (1,)
PY
peak_second=$(measure)
peak=$((peak_first > peak_second ? peak_first : peak_second))
printf 'Peak cgroup memory: %d bytes (%d MiB rounded up)\n' "$peak" "$(((peak + 1048575) / 1048576))"
# Reserve at least 20% of the cap during the synthetic smoke test.
test "$peak" -le $((256 * 1024 * 1024 * 80 / 100))

artifact="${RUNNER_TEMP:?}/pnec-image-artifact"
mkdir "$artifact"
docker save "$image" | gzip -1 > "$artifact/pnec-image.tar.gz"
{
  printf 'source_sha=%s\nplatform=linux/%s\nimage=%s\n' "$SOURCE_SHA" "$IMAGE_ARCH" "$image"
  printf 'image_id=%s\n' "$(docker image inspect --format '{{.Id}}' "$image")"
  printf 'memory_limit_bytes=268435456\nmemory_peak_bytes=%s\n' "$peak"
} > "$artifact/image-info.txt"
(cd "$artifact" && sha256sum pnec-image.tar.gz image-info.txt > SHA256SUMS)
cat "$artifact/image-info.txt" >> "${GITHUB_STEP_SUMMARY:?}"
