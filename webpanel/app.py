import asyncio
import math
import os
import re
import sys
import time
import uuid as uuid_lib
from contextlib import asynccontextmanager

from aiocryptopay import AioCryptoPay, Networks
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware
import bcrypt as bcrypt_lib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

from config import (  # noqa: E402
    ADMINS,
    BOT_TOKEN,
    BOT_USERNAME,
    CHANNEL,
    CRYPTO_TOKEN,
    SBP_TARIFFS,
    SESSION_SECRET,
    STARS_TARIFFS,
    SUPPORT,
    TARIFFS,
    WEB_URL,
)
from db import (  # noqa: E402
    add_days_to_user,
    add_time,
    apply_referral_bonus,
    bind_web_credentials_by_uuid,
    change_user_server,
    create_link_code,
    create_web_user,
    get_password_hash,
    get_user,
    get_user_by_uuid,
    get_user_by_web_username,
    get_user_profile,
    get_user_server_row,
    get_user_time_by_tg_id,
    init_db,
    invoice_already_processed,
    mark_invoice_processed,
    set_bonus_used,
    web_username_taken,
)
from keys import (  # noqa: E402
    generate_clash_profile,
    generate_vless,
    happ_open_html,
    make_happ_link,
)
from legal import PRIVACY_TEXT, TERMS_TEXT  # noqa: E402
from platega import (  # noqa: E402
    check_pending_sbp_payments,
    create_sbp_payment,
    fulfill_sbp_payment,
    get_transaction_status,
    pick,
    verify_callback_headers,
)
from servers import SERVERS  # noqa: E402
from vpn_logic import (  # noqa: E402
    apply_servers,
    can_change_server,
    get_best_server,
    get_time_left,
    list_servers,
)

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,24}$")
crypto = AioCryptoPay(token=CRYPTO_TOKEN, network=Networks.MAIN_NET)


async def check_crypto_payments():
    while True:
        try:
            invoices = await crypto.get_invoices(status="paid") or []
            for inv in invoices:
                if invoice_already_processed(inv.invoice_id):
                    continue
                try:
                    tg_id, plan = inv.description.split("|")
                    tg_id = int(tg_id)
                    tariff = TARIFFS[plan]
                except Exception:
                    continue
                if not add_time(tg_id, tariff["days"]):
                    continue
                mark_invoice_processed(inv.invoice_id)
                user = get_user(tg_id)
                if user:
                    await apply_servers(user[3])
                try:
                    await crypto.delete_invoice(inv.invoice_id)
                except Exception as e:
                    print("CRYPTO DELETE ERROR:", e)
        except Exception as e:
            print("WEB CRYPTO LOOP ERROR:", e)
        await asyncio.sleep(30)


async def check_sbp_payments():
    while True:
        try:
            await check_pending_sbp_payments(apply_servers)
        except Exception as e:
            print("WEB SBP LOOP ERROR:", e, flush=True)
        await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    tasks = [
        asyncio.create_task(check_crypto_payments()),
        asyncio.create_task(check_sbp_payments()),
    ]
    yield
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    try:
        await crypto.close()
    except Exception:
        pass


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="bushvpn_session",
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=False,
)


@app.get("/static/styles.css")
def static_css():
    return FileResponse(
        os.path.join(STATIC_DIR, "styles.css"),
        media_type="text/css",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/static/app.js")
def static_js():
    return FileResponse(
        os.path.join(STATIC_DIR, "app.js"),
        media_type="text/javascript",
        headers={"Cache-Control": "no-store"},
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class AuthData(BaseModel):
    username: str
    password: str
    accept: bool = False
    uuid: str | None = None
    ref: int | None = None


class ChangeServerData(BaseModel):
    server: str


class PayData(BaseModel):
    plan: str


class AdminDaysData(BaseModel):
    telegram_id: int
    days: int = Field(..., ge=-3650, le=3650)


def error(status: int, detail: str):
    raise HTTPException(status_code=status, detail=detail)


def find_server(name):
    return next((s for s in SERVERS if s["name"] == name), None)


def days_left(expires_at) -> int:
    seconds = (expires_at or 0) - int(time.time())
    return max(0, math.ceil(seconds / 86400)) if seconds > 0 else 0


def public_profile(profile: dict) -> dict:
    server = find_server(profile["server"])
    expires = int(profile["expires_at"] or 0)
    active = expires > int(time.time())
    vless = None
    happ = None
    if active and server:
        vless = generate_vless(profile["uuid"], server)
        happ = make_happ_link(vless, profile["uuid"], server["name"])
    left = days_left(expires)
    hours, minutes = (0, 0)
    if profile.get("last_server_change"):
        hours, minutes = get_time_left(profile["last_server_change"])
    return {
        "telegram_id": profile["telegram_id"],
        "web_username": profile["web_username"],
        "tg_username": profile["username"],
        "linked_telegram": profile["linked_telegram"],
        "server": profile["server"],
        "server_label": server["label"] if server else profile["server"],
        "expires_at": expires,
        "days_left": left,
        "active": active,
        "bonus_used": bool(profile["bonus_used"]),
        "ref_days": profile["ref_days"],
        "uuid": profile["uuid"] if active else None,
        "key": vless,
        "happ_link": happ,
        "can_change_server": can_change_server(profile.get("last_server_change")),
        "change_in_hours": hours,
        "change_in_minutes": minutes,
        "is_admin": profile["telegram_id"] in ADMINS,
        "bot_ref": f"https://t.me/{BOT_USERNAME}?start=ref-{profile['telegram_id']}",
        "web_ref": f"{WEB_URL}/?ref={profile['telegram_id']}",
        "channel": CHANNEL,
        "support": SUPPORT,
        "web_url": WEB_URL,
        "bot_username": BOT_USERNAME,
    }


def current_user(request: Request) -> dict:
    uid = request.session.get("uid")
    if not uid:
        error(401, "Нужно войти")
    profile = get_user_profile(int(uid))
    if not profile:
        request.session.clear()
        error(401, "Сессия недействительна")
    return profile


def optional_user(request: Request) -> dict | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    return get_user_profile(int(uid))


def hash_password(password: str) -> str:
    return bcrypt_lib.hashpw(password.encode("utf-8"), bcrypt_lib.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt_lib.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def validate_credentials(username: str, password: str):
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        error(400, "Логин: 3–24 символа, латиница, цифры и _")
    if not password or len(password) < 6:
        error(400, "Пароль должен быть не короче 6 символов")
    if len(password) > 72:
        error(400, "Пароль слишком длинный")
    return username, password


def login_session(request: Request, telegram_id: int):
    request.session.clear()
    request.session["uid"] = int(telegram_id)


@app.get("/")
def home():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/meta")
def meta(request: Request):
    user = optional_user(request)
    return {
        "web_url": WEB_URL,
        "bot": BOT_USERNAME,
        "channel": CHANNEL,
        "support": SUPPORT,
        "tariffs": TARIFFS,
        "sbp_tariffs": SBP_TARIFFS,
        "stars": STARS_TARIFFS,
        "user": public_profile(user) if user else None,
    }


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return public_profile(user)


@app.post("/api/auth/register")
async def register(data: AuthData, request: Request):
    username, password = validate_credentials(data.username, data.password)
    if not data.accept:
        error(400, "Нужно принять пользовательское соглашение")
    password_hash = hash_password(password)
    ref = data.ref if data.ref and data.ref != 0 else None

    if data.uuid:
        uuid_value = data.uuid.strip()
        telegram_id, err = bind_web_credentials_by_uuid(
            uuid_value, username, password_hash
        )
        if err:
            error(400, err)
        login_session(request, telegram_id)
        return public_profile(get_user_profile(telegram_id))

    if web_username_taken(username):
        error(400, "Такой логин уже занят")

    server = get_best_server()
    if server is None:
        error(503, "Все серверы переполнены")

    if ref:
        referrer = get_user_profile(ref)
        if not referrer:
            ref = None

    user_uuid = str(uuid_lib.uuid4())
    expires = int(time.time()) + 7 * 24 * 3600
    telegram_id = create_web_user(
        username,
        password_hash,
        user_uuid,
        expires,
        server["name"],
        referrer_id=ref,
    )
    await apply_servers(server["name"])
    if ref:
        bonus = apply_referral_bonus(telegram_id)
        if bonus:
            referrer = get_user_profile(ref)
            if referrer:
                await apply_servers(referrer["server"])
    login_session(request, telegram_id)
    profile = public_profile(get_user_profile(telegram_id))
    profile["trial"] = True
    return profile


@app.post("/api/auth/login")
def login(data: AuthData, request: Request):
    username, password = validate_credentials(data.username, data.password)
    profile = get_user_by_web_username(username)
    if not profile:
        error(401, "Неверный логин или пароль")
    stored = get_password_hash(profile["telegram_id"])
    if not stored or not verify_password(password, stored):
        error(401, "Неверный логин или пароль")
    login_session(request, profile["telegram_id"])
    return public_profile(get_user_profile(profile["telegram_id"]))


@app.post("/api/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.post("/api/account/link-code")
def link_code(user: dict = Depends(current_user)):
    if user["linked_telegram"]:
        error(400, "Telegram уже привязан")
    code, expires_at = create_link_code(user["telegram_id"])
    return {
        "code": code,
        "expires_at": expires_at,
        "command": f"/link {code}",
        "bot": f"https://t.me/{BOT_USERNAME}",
    }


@app.get("/api/servers")
def servers(user: dict = Depends(current_user)):
    return {"servers": list_servers(user["server"])}


@app.post("/api/servers/change")
async def change_server(data: ChangeServerData, user: dict = Depends(current_user)):
    row = get_user_server_row(user["telegram_id"])
    if not row:
        error(404, "Пользователь не найден")
    user_uuid, current_server, last_change = row
    if not can_change_server(last_change):
        hours, minutes = get_time_left(last_change)
        error(429, f"Сменить сервер можно через {hours}ч {minutes}м")
    if current_server == data.server:
        error(400, "Этот сервер уже выбран")
    new_server = find_server(data.server)
    if not new_server:
        error(404, "Сервер не найден")
    count_info = next(
        (s for s in list_servers() if s["name"] == data.server), None
    )
    if count_info and count_info["full"]:
        error(409, "Сервер переполнен")
    new_uuid = str(uuid_lib.uuid4())
    change_user_server(user["telegram_id"], new_uuid, data.server)
    await apply_servers(data.server, current_server)
    return public_profile(get_user_profile(user["telegram_id"]))


@app.post("/api/bonus")
async def claim_bonus(user: dict = Depends(current_user)):
    if user["bonus_used"]:
        error(400, "Бонус уже был использован")
    if not user["linked_telegram"]:
        error(
            400,
            "Привяжите Telegram и подпишитесь на канал, затем нажмите ещё раз",
        )
    subscribed = await telegram_subscribed(user["telegram_id"])
    if not subscribed:
        error(400, f"Сначала подпишитесь на канал {CHANNEL}")
    add_time(user["telegram_id"], 7)
    set_bonus_used(user["telegram_id"])
    await apply_servers(user["server"])
    return public_profile(get_user_profile(user["telegram_id"]))


async def telegram_subscribed(telegram_id: int) -> bool:
    import httpx

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            res = await client.get(
                url, params={"chat_id": CHANNEL, "user_id": telegram_id}
            )
            data = res.json()
        status = (data.get("result") or {}).get("status")
        return status in ("member", "administrator", "creator")
    except Exception:
        return False


@app.post("/api/pay/crypto")
async def pay_crypto(data: PayData, user: dict = Depends(current_user)):
    tariff = TARIFFS.get(data.plan)
    if not tariff:
        error(400, "Неизвестный тариф")
    invoice = await crypto.create_invoice(
        asset="USDT",
        amount=tariff["price"],
        description=f"{user['telegram_id']}|{data.plan}",
    )
    pay_url = getattr(invoice, "pay_url", None) or getattr(
        invoice, "bot_invoice_url", None
    )
    return {
        "invoice_id": invoice.invoice_id,
        "pay_url": pay_url,
        "bot_invoice_url": getattr(invoice, "bot_invoice_url", None),
        "title": tariff["title"],
        "price": tariff["price"],
        "currency": "USDT",
        "days": tariff["days"],
    }


@app.post("/api/pay/sbp")
async def pay_sbp(data: PayData, user: dict = Depends(current_user)):
    tariff = SBP_TARIFFS.get(data.plan)
    if not tariff:
        error(400, "Неизвестный тариф")
    username = user.get("web_username") or user.get("tg_username") or ""
    try:
        tx = await create_sbp_payment(
            user["telegram_id"],
            data.plan,
            username=username,
        )
    except Exception as e:
        error(502, f"Не удалось создать платёж: {e}")
    transaction_id = pick(tx, "transactionId", "id")
    redirect = pick(tx, "redirect")
    if not transaction_id or not redirect:
        error(502, "Platega не вернула ссылку на оплату")
    return {
        "invoice_id": transaction_id,
        "pay_url": redirect,
        "title": tariff["title"],
        "price": tariff["price"],
        "currency": "RUB",
        "days": tariff["days"],
    }


@app.post("/api/pay/platega/callback")
async def platega_callback(request: Request):
    if not verify_callback_headers(dict(request.headers)):
        print("PLATEGA CALLBACK UNAUTH", dict(request.headers), flush=True)
        error(401, "Unauthorized")
    try:
        body = await request.json()
    except Exception:
        error(400, "Invalid JSON")
    print("PLATEGA CALLBACK", body, flush=True)
    transaction_id = pick(body, "id", "transactionId")
    status = str(pick(body, "status") or "").upper()
    payload = pick(body, "payload") or ""
    if not transaction_id or status != "CONFIRMED":
        return {"ok": True}
    try:
        tx = await get_transaction_status(transaction_id)
    except Exception as e:
        print("PLATEGA CALLBACK VERIFY ERROR:", e, flush=True)
        error(502, "Failed to verify transaction")
    if str(pick(tx, "status") or "").upper() != "CONFIRMED":
        return {"ok": True}
    payload = pick(tx, "payload") or payload
    await fulfill_sbp_payment(transaction_id, payload, apply_servers)
    return {"ok": True}


@app.get("/api/pay/status/{invoice_id}")
async def pay_status(invoice_id: str, user: dict = Depends(current_user)):
    if invoice_already_processed(invoice_id):
        return {
            "paid": True,
            "user": public_profile(get_user_profile(user["telegram_id"])),
        }
    try:
        tx = await get_transaction_status(invoice_id)
        if str(pick(tx, "status") or "").upper() == "CONFIRMED":
            payload = pick(tx, "payload") or ""
            try:
                tg_id_str, _plan = payload.split("|", 1)
                if int(tg_id_str) != user["telegram_id"]:
                    error(403, "Нет доступа")
            except Exception:
                error(400, "Некорректный платёж")
            await fulfill_sbp_payment(invoice_id, payload, apply_servers, notify=False)
            return {
                "paid": True,
                "user": public_profile(get_user_profile(user["telegram_id"])),
            }
    except HTTPException:
        raise
    except Exception:
        pass
    paid = invoice_already_processed(invoice_id)
    return {
        "paid": paid,
        "user": public_profile(get_user_profile(user["telegram_id"])),
    }


@app.get("/api/legal/{kind}")
def legal(kind: str):
    if kind == "terms":
        return {"title": "Пользовательское соглашение", "text": TERMS_TEXT}
    if kind == "privacy":
        return {"title": "Политика конфиденциальности", "text": PRIVACY_TEXT}
    error(404, "Не найдено")


@app.post("/api/admin/adddays")
async def admin_adddays(data: AdminDaysData, user: dict = Depends(current_user)):
    if user["telegram_id"] not in ADMINS:
        error(403, "Нет доступа")
    if not add_days_to_user(data.telegram_id, data.days):
        error(404, "Пользователь не найден")
    target = get_user(data.telegram_id)
    if target:
        await apply_servers(target[3])
    left = get_user_time_by_tg_id(data.telegram_id)
    return {"ok": True, "days_left": left}


@app.get("/api/admin/time/{telegram_id}")
def admin_time(telegram_id: int, user: dict = Depends(current_user)):
    if user["telegram_id"] not in ADMINS:
        error(403, "Нет доступа")
    left = get_user_time_by_tg_id(telegram_id)
    if left is None:
        error(404, "Пользователь не найден")
    return {"days_left": left}


def _active_profile(user_uuid: str):
    row = get_user_by_uuid(user_uuid)
    if not row:
        error(404, "Key not found")
    telegram_id, uuid, expires_at, server_name = row
    if not expires_at or int(expires_at) <= int(time.time()):
        error(403, "Subscription expired")
    server = find_server(server_name)
    if not server:
        error(500, "Server not found")
    return uuid, expires_at, server


@app.get("/sub/{user_uuid}")
def clash_subscription(user_uuid: str):
    uuid, expires_at, server = _active_profile(user_uuid)
    body = generate_clash_profile(uuid, server, expires_at)
    headers = {
        "profile-update-interval": "24",
        "subscription-userinfo": f"upload=0; download=0; total=0; expire={int(expires_at)}",
        "content-disposition": f'attachment; filename="bushvpn-{server["name"].lower()}.yaml"',
    }
    return Response(content=body, media_type="text/plain; charset=utf-8", headers=headers)


def _happ_key_page(user_uuid: str):
    uuid, _expires_at, server = _active_profile(user_uuid)
    return HTMLResponse(
        happ_open_html(generate_vless(uuid, server)),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/key/{user_uuid}")
@app.get("/happ/{user_uuid}")
@app.get("/happ-sub/{user_uuid}")
def happ_import(user_uuid: str):
    return _happ_key_page(user_uuid)


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)



