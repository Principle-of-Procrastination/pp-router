#!/bin/sh
set -eu
cd /opt/pp-router/current
docker compose --env-file /opt/pp-router/shared/compose.env -f deploy/compose.yaml run --rm certbot renew --no-random-sleep-on-renew
docker compose --env-file /opt/pp-router/shared/compose.env -f deploy/compose.yaml exec -T web nginx -t
docker compose --env-file /opt/pp-router/shared/compose.env -f deploy/compose.yaml exec -T web nginx -s reload
