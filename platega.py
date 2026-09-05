import hmac
from typing import Any

import httpx

from config import PLATEGA_MERCHANT_ID, PLATEGA_SECRET, SBP_TARIFFS, WEB_URL
from db import (
    add_time,
    delete_pending_sbp,
    get_pending_sbp,
    get_user,
    invoice_already_processed,
    list_pending_sbp,
    mark_invoice_processed,
    save_pending_sbp,
)

PLATEGA_API = "https://app.platega.io"
DONE_STATUSES = {"CANCELED", "EXPIRED", "FAILED", "CHARGEBACKED"}


def pick(data: Any, *names: str):
    if not isinstance(data, dict):
        return None
    lower = {str(key).lower(): value for key, value in data.items()}
    for name in names:
        value = lower.get(name.lower())
        if value is not None and value != "":
            return value
    return None


def platega_headers() -> dict[str, str]:
    return {
        "X-MerchantId": PLATEGA_MERCHANT_ID,
        "X-Secret": PLATEGA_SECRET,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def verify_callback_headers(headers: dict[str, str]) -> bool:
    lower = {str(key).lower(): value or "" for key, value in headers.items()}
    merchant = lower.get("x-merchantid") or ""
    secret = lower.get("x-secret") or ""
    if not merchant or not secret:
        return False
    try:
        return hmac.compare_digest(merchant, PLATEGA_MERCHANT_ID) and hmac.compare_digest(
            secret, PLATEGA_SECRET
        )
    except ValueError:
        return False


def _payload_for(transaction_id: str, payload: str | None) -> str:
    if payload:
        return str(payload)
    pending = get_pending_sbp(transaction_id)
    if pending:
        return f"{pending['telegram_id']}|{pending['plan']}"
    return ""


async def create_sbp_payment(
    telegram_id: int,
    plan: str,
    username: str = "",
) -> dict[str, Any]:
    tariff = SBP_TARIFFS.get(plan)
    if not tariff:
        raise ValueError("Unknown plan")

    payload = f"{telegram_id}|{plan}"
    body = {
        "paymentMethod": 2,
        "paymentDetails": {
            "amount": tariff["price"],
            "currency": "RUB",
        },
        "description": f"BushVPN {tariff['title']}",
        "return": f"{WEB_URL}/?pay=success",
        "failedUrl": f"{WEB_URL}/?pay=fail",
        "payload": payload,
        "metadata": {
            "userId": str(telegram_id),
            "userName": username or str(telegram_id),
        },
    }
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{PLATEGA_API}/transaction/process",
            json=body,
            headers=platega_headers(),
        )
        res.raise_for_status()
        tx = res.json()

    transaction_id = pick(tx, "transactionId", "id")
    if transaction_id:
        save_pending_sbp(transaction_id, telegram_id, plan)
        tx["transactionId"] = transaction_id
    redirect = pick(tx, "redirect", "Redirect")
    if redirect:
        tx["redirect"] = redirect
    return tx


async def get_transaction_status(transaction_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(
            f"{PLATEGA_API}/transaction/{transaction_id}",
            headers=platega_headers(),
        )
        res.raise_for_status()
        return res.json()


async def notify_payment(tg_id: int, days: int) -> None:
    from config import BOT_TOKEN

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(
                url,
                json={
                    "chat_id": tg_id,
                    "text": f"✅ Оплата получена!\nВам начислено {days} дней.",
                },
            )
    except Exception:
        pass


async def fulfill_sbp_payment(
    transaction_id: str,
    payload: str,
    apply_servers_fn,
    *,
    notify: bool = True,
) -> bool:
    transaction_id = str(transaction_id)
    if invoice_already_processed(transaction_id):
        delete_pending_sbp(transaction_id)
        return False
    payload = _payload_for(transaction_id, payload)
    try:
        tg_id_str, plan = payload.split("|", 1)
        tg_id = int(tg_id_str)
        tariff = SBP_TARIFFS[plan]
    except Exception:
        print("PLATEGA FULFILL PARSE ERROR:", transaction_id, payload, flush=True)
        return False
    if not add_time(tg_id, tariff["days"]):
        print("PLATEGA FULFILL USER NOT FOUND:", tg_id, flush=True)
        return False
    mark_invoice_processed(transaction_id)
    delete_pending_sbp(transaction_id)
    user = get_user(tg_id)
    if user:
        await apply_servers_fn(user[3])
    if notify:
        await notify_payment(tg_id, tariff["days"])
    return True


async def check_pending_sbp_payments(apply_servers_fn) -> None:
    for pending in list_pending_sbp():
        transaction_id = pending["transaction_id"]
        if invoice_already_processed(transaction_id):
            delete_pending_sbp(transaction_id)
            continue
        try:
            tx = await get_transaction_status(transaction_id)
        except Exception as e:
            print("PLATEGA STATUS ERROR:", transaction_id, e, flush=True)
            continue
        status = str(pick(tx, "status") or "").upper()
        if status == "CONFIRMED":
            payload = pick(tx, "payload") or f"{pending['telegram_id']}|{pending['plan']}"
            await fulfill_sbp_payment(transaction_id, payload, apply_servers_fn)
        elif status in DONE_STATUSES:
            delete_pending_sbp(transaction_id)
