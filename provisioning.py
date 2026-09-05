import hashlib
import json
import os
import threading
import time

import paramiko

from db import (
    BASE_DIR,
    clear_dirty,
    get_active_uuids,
    get_dirty_servers,
    get_sync_hash,
    mark_server_dirty,
    set_sync_hash,
)
from servers import SERVERS

GENERATED_DIR = os.path.join(BASE_DIR, "generated")
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _server_lock(server_name):
    with _LOCKS_GUARD:
        if server_name not in _LOCKS:
            _LOCKS[server_name] = threading.Lock()
        return _LOCKS[server_name]


def find_server(server_name):
    return next((s for s in SERVERS if s["name"] == server_name), None)


def users_hash(uuids):
    payload = ",".join(sorted(uuids))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def template_hash(server):
    template_path = os.path.join(BASE_DIR, server["template"])
    with open(template_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def desired_state_hash(server, uuids):
    payload = f"{template_hash(server)}:{users_hash(uuids)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ssh_run(ssh, command, timeout=60):
    stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def open_ssh(server):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=server["ip"],
        username=server["ssh_user"],
        password=server["ssh_pass"],
        timeout=15,
        banner_timeout=15,
        auth_timeout=15,
        look_for_keys=False,
        allow_agent=False,
    )
    return ssh


def generate_config(server):
    template_path = os.path.join(BASE_DIR, server["template"])
    with open(template_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    uuids = get_active_uuids(server["name"])
    users = [{"uuid": uuid, "flow": "xtls-rprx-vision"} for uuid in uuids]
    for inbound in config.get("inbounds", []):
        if inbound.get("type") == "vless":
            inbound["users"] = users

    os.makedirs(GENERATED_DIR, exist_ok=True)
    generated_path = os.path.join(GENERATED_DIR, f"{server['name'].lower()}.json")
    with open(generated_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return generated_path, uuids


def configs_equal(local_path, remote_content):
    with open(local_path, "r", encoding="utf-8") as f:
        local = json.loads(f.read())
    remote = json.loads(remote_content)
    return local == remote


def upload_and_reload(server, generated_path):
    ssh = open_ssh(server)
    try:
        code, remote_content, err = ssh_run(ssh, f"cat {server['output']}")
        if code == 0 and remote_content.strip():
            try:
                if configs_equal(generated_path, remote_content):
                    print(f"{server['name']} unchanged, skip reload")
                    return "unchanged"
            except json.JSONDecodeError:
                print(f"{server['name']} remote config is not valid JSON, rewriting")

        temp_path = "/tmp/sing-box-config.json"
        sftp = ssh.open_sftp()
        try:
            sftp.put(generated_path, temp_path)
        finally:
            sftp.close()

        code, out, err = ssh_run(ssh, f"sing-box check -c {temp_path}")
        if code != 0:
            raise RuntimeError(
                f"sing-box check failed on {server['name']}: {err or out}"
            )

        code, out, err = ssh_run(
            ssh, f"install -m 644 {temp_path} {server['output']}"
        )
        if code != 0:
            code, out, err = ssh_run(
                ssh,
                f"mv {temp_path} {server['output']} && chmod 644 {server['output']}",
            )
            if code != 0:
                raise RuntimeError(
                    f"failed to install config on {server['name']}: {err or out}"
                )

        code, out, err = ssh_run(ssh, "systemctl reload sing-box")
        if code != 0:
            print(f"{server['name']} reload failed, trying restart: {err or out}")
            code, out, err = ssh_run(ssh, "systemctl restart sing-box")
            if code != 0:
                raise RuntimeError(
                    f"sing-box reload/restart failed on {server['name']}: {err or out}"
                )

        code, out, err = ssh_run(ssh, "systemctl is-active sing-box")
        if out.strip() != "active":
            raise RuntimeError(
                f"sing-box is not active on {server['name']}: {out or err}"
            )

        print(f"{server['name']} config applied")
        return "reloaded"
    finally:
        ssh.close()


def sync_server(server_name, force=False):
    server = find_server(server_name)
    if not server:
        print(f"Server {server_name} not found")
        return False

    with _server_lock(server_name):
        print(f"Syncing {server_name}")
        generated_path, uuids = generate_config(server)
        desired_hash = desired_state_hash(server, uuids)

        if not force and get_sync_hash(server_name) == desired_hash:
            print(f"Done {server_name} (already in sync, {len(uuids)} users)")
            return True

        result = upload_and_reload(server, generated_path)
        set_sync_hash(server_name, desired_hash)
        print(f"Done {server_name} ({result}, {len(uuids)} users)")
        return True


def sync_dirty_servers():
    dirty = get_dirty_servers()
    if not dirty:
        return

    print("DIRTY SERVERS:", [name for name, _ in dirty])
    for server_name, generation in dirty:
        try:
            sync_server(server_name)
            clear_dirty(server_name, generation)
        except Exception as e:
            print(f"SYNC ERROR {server_name}:", e)


def mark_servers_if_set_changed():
    for server in SERVERS:
        uuids = get_active_uuids(server["name"])
        desired = desired_state_hash(server, uuids)
        current = get_sync_hash(server["name"])
        if current != desired:
            print(
                f"{server['name']} desired state changed "
                f"({len(uuids)} active), marking dirty"
            )
            mark_server_dirty(server["name"])


def sync_all_servers(force=False):
    for server in SERVERS:
        try:
            sync_server(server["name"], force=force)
            clear_dirty(server["name"])
        except Exception as e:
            print(f"SYNC ERROR {server['name']}:", e)


def worker_loop(interval=30):
    print("Sync worker started")
    print("SERVERS:", [s["name"] for s in SERVERS])
    while True:
        try:
            mark_servers_if_set_changed()
            sync_dirty_servers()
        except Exception as e:
            print("WORKER LOOP ERROR:", e)
        time.sleep(interval)
