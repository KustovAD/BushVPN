import asyncio
import time

from db import get_server_users, mark_server_dirty
from provisioning import sync_server
from servers import SERVERS

SERVER_COOLDOWN = 5 * 3600


def get_best_server(exclude=None):
    best_server = None
    min_load = 9999
    for server in SERVERS:
        if exclude and server["name"] == exclude:
            continue
        count = get_server_users(server["name"])
        if count >= server["limit"]:
            continue
        load = count / server["limit"]
        if load < min_load:
            min_load = load
            best_server = server
    return best_server


def can_change_server(last_change):
    if not last_change:
        return True
    return (int(time.time()) - last_change) >= SERVER_COOLDOWN


def get_time_left(last_change):
    now = int(time.time())
    left = SERVER_COOLDOWN - (now - last_change)
    if left <= 0:
        return 0, 0
    return left // 3600, (left % 3600) // 60


def server_load_status(name):
    server = next((s for s in SERVERS if s["name"] == name), None)
    if not server:
        return None
    count = get_server_users(server["name"])
    limit = server["limit"]
    load = count / limit if limit else 1
    if load < 0.7:
        status = "green"
    elif load < 0.9:
        status = "yellow"
    else:
        status = "red"
    return {
        "name": server["name"],
        "label": server["label"],
        "count": count,
        "limit": limit,
        "full": count >= limit,
        "status": status,
        "load_pct": round(load * 100),
    }


def list_servers(current_server=None):
    items = []
    for server in SERVERS:
        item = server_load_status(server["name"])
        item["current"] = server["name"] == current_server
        items.append(item)
    return items


def apply_server_sync(server_name):
    if not server_name:
        return
    mark_server_dirty(server_name)
    try:
        sync_server(server_name)
    except Exception as e:
        print(f"APPLY ERROR {server_name}:", e)


async def apply_servers(*server_names):
    seen = []
    for name in server_names:
        if not name or name in seen:
            continue
        seen.append(name)
        await asyncio.to_thread(apply_server_sync, name)
