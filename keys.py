import base64
import json
from urllib.parse import quote

REALITY_SNI = "www.cloudflare.com"
PANEL_URL = "https://bushvpns.duckdns.org"
HAPP_IMPORT_BASE = "https://happbushvpns.duckdns.org"


def _sni(server):
    return server.get("sni") or REALITY_SNI


def happ_display_name(server):
    label = server.get("label") or ""
    chars = list(label)
    if len(chars) >= 2 and "\U0001F1E6" <= chars[0] <= "\U0001F1FF":
        flag = "".join(chars[:2])
        country = "".join(chars[2:]).strip()
        if country:
            return f"{flag} BushVPN {country}"
    return f"BushVPN {server.get('name', 'VPN')}"


def generate_vless(user_uuid, server, display_name=None):
    remark = display_name or happ_display_name(server)
    return (
        f"vless://{user_uuid}@{server['ip']}:{server['port']}"
        f"?type=tcp"
        f"&encryption=none"
        f"&security=reality"
        f"&pbk={server['pbk']}"
        f"&fp=chrome"
        f"&sni={_sni(server)}"
        f"&sid={server['sid']}"
        f"&flow=xtls-rprx-vision"
        f"&packetEncoding=xudp"
        f"&mux=0"
        f"&fragment=tlshello"
        f"#{remark}"
    )


def generate_happ_vless(user_uuid, server):
    return generate_vless(user_uuid, server)


def happ_deeplink(vless_key):
    encoded = quote(vless_key, safe="")
    return f"happ://import/{encoded}"


def happ_intent_link(vless_key):
    encoded = quote(vless_key, safe="")
    return (
        f"intent://import/{encoded}#Intent;scheme=happ;package=com.happproxy;end"
    )


def happ_open_html(vless_key):
    happ = happ_deeplink(vless_key)
    intent = happ_intent_link(vless_key)
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <meta http-equiv="refresh" content="0;url={happ}">
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


def generate_clash_profile(user_uuid, server, expires_at=None):
    name = f"BushVPN-{server['name']}"
    sni = _sni(server)
    return f"""mixed-port: 7890
allow-lan: false
bind-address: "*"
mode: rule
log-level: warning
ipv6: false
unified-delay: true
tcp-concurrent: false
profile:
  store-selected: true
dns:
  enable: true
  ipv6: false
  listen: 0.0.0.0:1053
  enhanced-mode: redir-host
  default-nameserver:
    - 77.88.8.8
    - 1.1.1.1
  nameserver:
    - https://1.1.1.1/dns-query
    - https://8.8.8.8/dns-query
  nameserver-policy:
    "geosite:category-ru":
      - 77.88.8.8
      - 8.8.8.8
    "geosite:yandex":
      - 77.88.8.8
    "geosite:mailru":
      - 77.88.8.8
    "geosite:vk":
      - 77.88.8.8
proxies:
  - name: {name}
    type: vless
    server: {server["ip"]}
    port: {server["port"]}
    uuid: {user_uuid}
    network: tcp
    udp: true
    tls: true
    flow: xtls-rprx-vision
    servername: {sni}
    client-fingerprint: chrome
    packet-encoding: xudp
    tfo: false
    smux:
      enabled: false
    reality-opts:
      public-key: {server["pbk"]}
      short-id: {server["sid"]}
proxy-groups:
  - name: PROXY
    type: select
    proxies:
      - {name}
rules:
  - GEOIP,private,DIRECT,no-resolve
  - GEOSITE,private,DIRECT
  - GEOSITE,category-ru,DIRECT
  - GEOSITE,yandex,DIRECT
  - GEOSITE,mailru,DIRECT
  - GEOSITE,vk,DIRECT
  - GEOIP,RU,DIRECT
  - DOMAIN-SUFFIX,gosuslugi.ru,DIRECT
  - DOMAIN-SUFFIX,nalog.ru,DIRECT
  - DOMAIN-SUFFIX,sberbank.ru,DIRECT
  - DOMAIN-SUFFIX,sber.ru,DIRECT
  - DOMAIN-SUFFIX,tbank.ru,DIRECT
  - DOMAIN-SUFFIX,tinkoff.ru,DIRECT
  - DOMAIN-SUFFIX,vtb.ru,DIRECT
  - DOMAIN-SUFFIX,alfabank.ru,DIRECT
  - DOMAIN-SUFFIX,cbr.ru,DIRECT
  - DOMAIN-SUFFIX,mos.ru,DIRECT
  - DOMAIN-SUFFIX,mosreg.ru,DIRECT
  - DOMAIN-SUFFIX,esia.gosuslugi.ru,DIRECT
  - DOMAIN-SUFFIX,max.ru,DIRECT
  - DOMAIN-SUFFIX,ok.ru,DIRECT
  - DOMAIN-SUFFIX,mail.ru,DIRECT
  - DOMAIN-SUFFIX,yandex.ru,DIRECT
  - DOMAIN-SUFFIX,yandex.net,DIRECT
  - DOMAIN-SUFFIX,ya.ru,DIRECT
  - DOMAIN-SUFFIX,dzen.ru,DIRECT
  - DOMAIN-SUFFIX,vk.com,DIRECT
  - DOMAIN-SUFFIX,vk.ru,DIRECT
  - DOMAIN-SUFFIX,userapi.com,DIRECT
  - DOMAIN-SUFFIX,wildberries.ru,DIRECT
  - DOMAIN-SUFFIX,ozon.ru,DIRECT
  - DOMAIN-SUFFIX,avito.ru,DIRECT
  - DOMAIN-SUFFIX,rutube.ru,DIRECT
  - DOMAIN-SUFFIX,2gis.ru,DIRECT
  - DOMAIN-SUFFIX,hh.ru,DIRECT
  - DOMAIN-SUFFIX,rustore.ru,DIRECT
  - MATCH,PROXY
"""


def make_happ_link(vless_key, user_uuid=None, server_name=None):
    if user_uuid and server_name:
        return f"{HAPP_IMPORT_BASE}/i/{server_name}/{user_uuid}"
    if user_uuid:
        return f"{HAPP_IMPORT_BASE}/i/{user_uuid}"
    payload = (
        base64.urlsafe_b64encode(vless_key.encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )
    return f"{HAPP_IMPORT_BASE}/i/{payload}"

