#!/bin/bash
set -euo pipefail

ROOT="/root/bushvpn/happ_import"
INC_SRC="$ROOT/happ-stub-locations.conf"
INC_DST="/etc/nginx/happ-stub-locations.conf"
VHOST_SRC="$ROOT/nginx-happbushvpn.conf"
VHOST_DST="/etc/nginx/conf.d/happbushvpns.duckdns.org.conf"
UNIT_SRC="$ROOT/bushvpn-happ.service"
NGINX_CONF="/etc/nginx/nginx.conf"

if [[ ! -f "$INC_SRC" || ! -f "$VHOST_SRC" || ! -f "$UNIT_SRC" ]]; then
  echo "Missing files in $ROOT"
  exit 1
fi

cp "$INC_SRC" "$INC_DST"
mkdir -p /etc/nginx/conf.d
cp "$VHOST_SRC" "$VHOST_DST"

python3 - << 'PY'
from pathlib import Path

p = Path("/etc/nginx/nginx.conf")
t = p.read_text()
changed = False

loc = "        include /etc/nginx/happ-stub-locations.conf;\n"
if "happ-stub-locations.conf" not in t:
    needle = "        listen 8443 ssl;\n"
    if needle not in t:
        needle = "        listen 8443 ssl http2;\n"
    if needle in t:
        t = t.replace(needle, needle + loc, 1)
        changed = True
        print("injected /i/ and /health into nginx.conf :8443 website")
    else:
        print("WARN: could not find listen 8443 in nginx.conf")

vhost = "    include /etc/nginx/conf.d/happbushvpns.duckdns.org.conf;\n"
if "happbushvpns.duckdns.org.conf" not in t:
    marker = "    # HTTPS на порту 8443\n"
    if marker in t:
        t = t.replace(marker, vhost + marker, 1)
        changed = True
        print("included happbushvpns vhost in http {}")
    else:
        # last-resort: before first 8443 server
        marker2 = "    server {\n        listen 8443 ssl;"
        if marker2 in t:
            t = t.replace(marker2, vhost + marker2, 1)
            changed = True
            print("included happbushvpns vhost before 8443 server")

if changed:
    p.write_text(t)
PY

echo "=== Install happ_import service ==="
cp "$UNIT_SRC" /etc/systemd/system/bushvpn-happ.service
/root/bushvpn/venv/bin/pip -q install fastapi uvicorn
systemctl daemon-reload
systemctl enable --now bushvpn-happ
systemctl restart bushvpn-happ
sleep 1

nginx -t
systemctl reload nginx

echo
echo "Local happ app:"
curl -sS http://127.0.0.1:8090/health
echo
echo "Website domain /health (must be JSON, not login HTML):"
curl -sk https://bushvpns.duckdns.org:8443/health
echo
echo "Happ domain /health:"
curl -sk https://happbushvpns.duckdns.org:8443/health || true
echo
