#!/bin/sh
set -eu

cd /opt/ai-council-os/current

api_ip="$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ai-council-os-api-1)"

public_host="187.124.172.17.sslip.io"
health_code="$(curl -sS -H "Host: ${public_host}" -o /tmp/council-health.json -w '%{http_code}' "http://${api_ip}:8000/healthz")"
ready_code="$(curl -sS -H "Host: ${public_host}" -o /tmp/council-ready.json -w '%{http_code}' "http://${api_ip}:8000/readyz")"
printf 'health=%s\nready=%s\n' "$health_code" "$ready_code"
head -c 2000 /tmp/council-ready.json
printf '\n'

docker compose exec -T postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select id,is_enabled,is_paused from workflow_definitions order by id;"'

docker compose exec -T backup sh -c \
  'ls -lh /backups; find /backups -maxdepth 1 -type f -name "*.dump" -size +0c | sort | tail -n 1'
