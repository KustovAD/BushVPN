import os
import sys
import json
import time
import base64
import re
from urllib.parse import quote, unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from keys import generate_vless
from servers import SERVERS

try:
    from db import get_user_by_uuid
except Exception:
    get_user_by_uuid = None

app = FastAPI()

HAPP_LIST = "BushVPN🪴"
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}


@app.exception_handler(HTTPException)
def html_errors(request: Request, exc: HTTPException):
    accept = request.headers.get("accept") or ""
    if "text/html" in accept or "Mozilla" in (request.headers.get("user-agent") or ""):
        return HTMLResponse(
            f"<!DOCTYPE html><html><body style='font-family:sans-serif;"
            f"background:#0f1410;color:#c8d4cc;padding:40px'>"
            f"<p>{exc.detail}</p></body></html>",
            status_code=exc.status_code,
            headers=HEADERS,
        )
    return PlainTextResponse(exc.detail, status_code=exc.status_code)


def decode_payload(payload: str) -> str:
    raw = unquote(payload).strip()
    if raw.startswith("vless://"):
        return raw
    pad = "=" * (-len(raw) % 4)
    try:
        decoded = base64.urlsafe_b64decode(raw + pad).decode("utf-8")
    except Exception:
        raise HTTPException(400, "Invalid config")
    if not decoded.startswith(("vless://", "hy2://", "hysteria2://", "ss://", "trojan://")):
        raise HTTPException(400, "Invalid config")
    return decoded


def find_server(name: str):
    key = (name or "").lower()
    return next((s for s in SERVERS if s["name"].lower() == key), None)


def vless_from_server_and_uuid(server_name: str, user_uuid: str) -> str:
    server = find_server(server_name)
    if not server:
        raise HTTPException(404, "Key not found")
    return generate_vless(user_uuid, server)


def vless_from_uuid(user_uuid: str) -> str:
    if get_user_by_uuid is None:
        raise HTTPException(404, "Key not found")
    row = get_user_by_uuid(user_uuid)
    if not row:
        raise HTTPException(404, "Key not found")
    _telegram_id, uuid, expires_at, server_name = row
    if not expires_at or int(expires_at) <= int(time.time()):
        raise HTTPException(403, "Subscription expired")
    server = find_server(server_name)
    if not server:
        raise HTTPException(500, "Server not found")
    return generate_vless(uuid, server)


def config_from_payload(payload: str) -> str:
    raw = unquote(payload).strip().strip("/")
    parts = raw.split("/")
    if len(parts) == 2 and UUID_RE.match(parts[1]):
        return vless_from_server_and_uuid(parts[0], parts[1])
    if UUID_RE.match(raw):
        return vless_from_uuid(raw)
    return decode_payload(raw)


def happ_subscription(config: str) -> str:
    key = unquote(config.strip())
    return (
        f"#profile-title: {HAPP_LIST}\n"
        "#fragmentation-enable: 1\n"
        "#fragmentation-packets: tlshello\n"
        "#fragmentation-length: 50-100\n"
        "#fragmentation-interval: 10-20\n"
        f"{key}\n"
    )


def page(config: str) -> str:
    body = happ_subscription(config)
    happ = "happ://add/" + quote(body, safe="")
    intent = (
        "intent://add/"
        + quote(body, safe="")
        + "#Intent;scheme=happ;package=com.happproxy;end"
    )
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <title>Открыть Happ</title>
  <style>
    body {{ margin: 0; min-height: 100vh; display: flex; flex-direction: column;
           align-items: center; justify-content: center; gap: 16px;
           font-family: sans-serif; background: #0f1410; color: #c8d4cc; }}
    a {{ color: #fff; background: #2f6b3a; text-decoration: none;
        padding: 16px 28px; border-radius: 12px; font-size: 18px; }}
    p {{ margin: 0; font-size: 14px; opacity: .7; }}
  </style>
</head>
<body>
  <a id="open" href="{happ}">Открыть в Happ</a>
  <p>Если приложение не открылось — нажмите кнопку</p>
  <script>
    const happ = {json.dumps(happ)};
    const intent = {json.dumps(intent)};
    const ua = navigator.userAgent || "";
    const target = /Android/i.test(ua) ? intent : happ;
    const a = document.getElementById("open");
    a.href = target;
    function go() {{ location.href = target; }}
    go();
    setTimeout(go, 400);
  </script>
</body>
</html>"""


@app.get("/")
def from_query(request: Request, config: str = ""):
    if not config:
        return HTMLResponse("<!DOCTYPE html><html><body></body></html>", headers=HEADERS)
    return HTMLResponse(page(decode_payload(config)), headers=HEADERS)


@app.get("/i/{payload:path}")
def from_path(payload: str, request: Request):
    return HTMLResponse(page(config_from_payload(payload)), headers=HEADERS)


@app.get("/health")
def health():
    return {"ok": True}
