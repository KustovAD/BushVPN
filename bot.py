from html import escape as html_escape

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    PreCheckoutQueryHandler,
    MessageHandler,
    filters,
)

from aiocryptopay import AioCryptoPay, Networks

import asyncio
import math
import time
import uuid as uuid_lib

from config import (
    ADMINS,
    BOT_TOKEN,
    BOT_USERNAME,
    CHANNEL,
    CRYPTO_TOKEN,
    SBP_TARIFFS,
    STARS_TARIFFS,
    TARIFFS,
    WEB_URL,
)
from db import (
    add_days_to_user,
    add_or_update_user,
    add_time,
    apply_referral_bonus,
    change_user_server,
    consume_link_code,
    get_user,
    get_user_server_row,
    get_user_time_by_tg_id,
    init_db,
    invoice_already_processed,
    mark_invoice_processed,
    set_bonus_used,
    update_user_username,
)
from keys import generate_vless, make_happ_link
from legal import PRIVACY_TEXT, TERMS_TEXT, split_legal
from platega import check_pending_sbp_payments, create_sbp_payment, pick
from servers import SERVERS
from vpn_logic import apply_servers, can_change_server, get_best_server, get_time_left, list_servers

crypto = AioCryptoPay(token=CRYPTO_TOKEN, network=Networks.MAIN_NET)


def is_admin(user_id):
    return user_id in ADMINS


def get_server_buttons(current_server):
    keyboard = []
    status_icon = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
    for server in list_servers(current_server):
        text = f"{status_icon.get(server['status'], '🟢')} {server['label']}"
        if server["current"]:
            text += " ✅"
        callback = "full" if server["full"] else f"select_{server['name']}"
        keyboard.append([InlineKeyboardButton(text, callback_data=callback)])
    keyboard.append([InlineKeyboardButton("⬅ Назад", callback_data="back")])
    return InlineKeyboardMarkup(keyboard)


async def is_subscribed(bot, user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False


async def adddays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    if not is_admin(tg_id):
        await update.message.reply_text("❌ Нет доступа")
        return
    if len(context.args) != 2:
        await update.message.reply_text(
            "Использование:\n/adddays TG_ID ДНИ\n\nПример:\n/adddays 123456789 30"
        )
        return
    target_id = int(context.args[0])
    days = int(context.args[1])
    add_days_to_user(target_id, days)
    user = get_user(target_id)
    if user:
        await apply_servers(user[3])
    await update.message.reply_text(f"✅ Пользователю {target_id} добавлено {days} дней")


async def check_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /time 123456789")
        return
    try:
        tg_id = int(context.args[0])
    except Exception:
        await update.message.reply_text("Неверный TG ID")
        return
    days_left = get_user_time_by_tg_id(tg_id)
    if days_left is None:
        await update.message.reply_text("Пользователь не найден")
        return
    if days_left == 0:
        await update.message.reply_text("Подписка истекла")
        return
    await update.message.reply_text(f"Осталось дней: {days_left}")


def main_menu():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💳 Пополнить", callback_data="pay")],
            [InlineKeyboardButton("📘 Как подключиться", callback_data="how")],
            [InlineKeyboardButton("🔑 Получить ключ", callback_data="key")],
            [InlineKeyboardButton("🌍 Сменить сервер", callback_data="servers")],
            [InlineKeyboardButton("🎁 Бонус +7 дней", callback_data="bonus")],
            [InlineKeyboardButton("🔗 Пригласить друга", callback_data="ref")],
            [InlineKeyboardButton("👤 Мой аккаунт", callback_data="account")],
            [InlineKeyboardButton("❓ Вопросы / Поддержка", callback_data="faq")],
        ]
    )


def back_button():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅ Назад", callback_data="back")]]
    )


def faq_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Соглашение", callback_data="terms"),
                InlineKeyboardButton("Конфиденциальность", callback_data="privacy"),
            ],
            [InlineKeyboardButton("⬅ Назад", callback_data="back")],
        ]
    )


def legal_keyboard(kind="terms", page=0, pages=1):
    rows = []
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(
                InlineKeyboardButton("◀", callback_data=f"legal:{kind}:{page - 1}")
            )
        nav.append(
            InlineKeyboardButton(f"{page + 1}/{pages}", callback_data="legal_noop")
        )
        if page < pages - 1:
            nav.append(
                InlineKeyboardButton("▶", callback_data=f"legal:{kind}:{page + 1}")
            )
        rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton("Соглашение", callback_data="terms"),
            InlineKeyboardButton("Конфиденциальность", callback_data="privacy"),
        ]
    )
    rows.append([InlineKeyboardButton("⬅ Назад", callback_data="faq")])
    return InlineKeyboardMarkup(rows)


def happ_keyboard(vless_key, user_uuid=None, server_name=None):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🚀 Подключить в Happ",
                    url=make_happ_link(vless_key, user_uuid, server_name),
                )
            ],
            [InlineKeyboardButton("⬅ Назад", callback_data="back")],
        ]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    tg_username = update.effective_user.username
    args = context.args
    now = int(time.time())

    if tg_username:
        update_user_username(tg_id, tg_username)

    referrer_id = None
    if args:
        start_arg = args[0]
        if start_arg.startswith("ref-"):
            referrer_id = int(start_arg.replace("ref-", ""))

    if referrer_id == tg_id:
        referrer_id = None

    user = get_user(tg_id)
    is_new_user = False

    if user is None:
        is_new_user = True
        user_uuid = str(uuid_lib.uuid4())
        expires = now + 7 * 24 * 3600
        server = get_best_server()

        if server is None:
            await update.message.reply_text("❌ Все серверы переполнены")
            return

        add_or_update_user(
            tg_id,
            user_uuid,
            expires,
            referrer_id=referrer_id,
            server=server["name"],
        )
        await apply_servers(server["name"])

        if referrer_id:
            bonus = apply_referral_bonus(tg_id)
            if bonus > 0:
                referrer = get_user(referrer_id)
                if referrer:
                    await apply_servers(referrer[3])
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text="🎉 Вам начислено +5 дней за приглашение",
                )

    if is_new_user:
        await update.message.reply_text("🎁 Вам автоматически выдано 7 дней бесплатно")

    text = (
        "🌿 BushVPN\n\n"
        "Надёжный и быстрый VPN\n"
        "Выберите действие 👇\n\n"
        "Используя бота, вы принимаете условия сервиса."
    )
    await update.message.reply_text(text, reply_markup=main_menu())


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tg_id = query.from_user.id
    now = int(time.time())

    if query.from_user.username:
        update_user_username(tg_id, query.from_user.username)

    if query.data == "back":
        await query.edit_message_text("Главное меню 👇", reply_markup=main_menu())

    elif query.data == "how":
        await query.edit_message_text(
            "📘 <b>Подключение BushVPN</b>\n\n"
            "📱 <b>Шаг 1.</b> Установите Happ:\n"
            "• <a href='https://apps.apple.com/app/happ-proxy-utility/id6504287215'>iPhone / iPad</a>\n"
            "• <a href='https://play.google.com/store/apps/details?id=com.happproxy'>Android</a>\n\n"
            "🔑 <b>Шаг 2.</b> В главном меню нажмите <b>«Получить ключ»</b>\n\n"
            "🚀 <b>Шаг 3.</b> Нажмите <b>«Подключить в Happ»</b>\n"
            "или скопируйте ключ и добавьте его в Happ.\n\n"
            "🛡 <b>Шаг 4.</b> В настройках Happ включите <b>фрагментирование</b>,\n"
            "чтобы лучше обходить глушилку.\n\n"
            "✅ <b>Шаг 5.</b> Включите VPN.\n\n"
            "🌍 Готово!",
            reply_markup=back_button(),
            parse_mode="HTML",
        )

    elif query.data == "faq":
        await query.edit_message_text(
            "❓ <b>Частые вопросы</b>\n\n"
            "📱 <b>Нет Happ (iOS)?</b>\n"
            "Смените регион App Store\n\n"
            "🌐 <b>Плохая скорость?</b>\n"
            "В Happ включите режим TUN и DNS:\n"
            "• Remote DNS: <code>https://1.1.1.1/dns-query</code>\n"
            "• Direct DNS: <code>1.1.1.1</code>\n\n"
            "<b>⚠️ Ошибка добавления ключа?</b>\n"
            "Перезапустите Happ и импортируйте ключ заново\n\n"
            "💻 <b>Проблемы на ПК?</b>\n"
            "Запускайте от имени администратора → режим службы: Системный VPN\n\n"
            "📱 <b>Не работает TikTok?</b>\n"
            "Очистите кэш → закройте TikTok → подождите 10 сек → зайдите с VPN\n\n"
            "🆘 <b>Поддержка:</b> @BushVPN_Support",
            reply_markup=faq_keyboard(),
            parse_mode="HTML",
        )

    elif query.data == "legal_noop":
        return

    elif query.data in ("terms", "privacy") or query.data.startswith("legal:"):
        if query.data.startswith("legal:"):
            _, kind, page_s = query.data.split(":")
            page = int(page_s)
        else:
            kind = query.data
            page = 0
        text = TERMS_TEXT if kind == "terms" else PRIVACY_TEXT
        chunks = split_legal(text)
        page = max(0, min(page, len(chunks) - 1))
        try:
            await query.edit_message_text(
                chunks[page],
                reply_markup=legal_keyboard(kind, page, len(chunks)),
            )
        except Exception:
            pass

    elif query.data == "servers":
        user = get_user(tg_id)
        current_server = user[3] if user else None
        keyboard = get_server_buttons(current_server)
        await query.edit_message_text("🌍 Выберите сервер:", reply_markup=keyboard)

    elif query.data.startswith("select_"):
        server_name = query.data.replace("select_", "")
        row = get_user_server_row(tg_id)

        if not row:
            await query.message.reply_text("❌ Пользователь не найден")
            return

        user_uuid, current_server, last_change = row

        if not can_change_server(last_change):
            hours, minutes = get_time_left(last_change)
            await query.message.reply_text(
                f"⏳ Сменить сервер можно через {hours}ч {minutes}м"
            )
            return

        if current_server == server_name:
            await query.message.reply_text("⚠️ У вас уже выбран этот сервер")
            return

        new_server = next((s for s in SERVERS if s["name"] == server_name), None)
        if not new_server:
            await query.message.reply_text("❌ Сервер не найден")
            return

        new_uuid = str(uuid_lib.uuid4())
        change_user_server(tg_id, new_uuid, server_name)

        key = generate_vless(new_uuid, new_server)
        await query.message.reply_text(
            f"✅ Сервер изменён: {html_escape(new_server['label'])}\n\n"
            f"🔑 Ваш ключ:\n\n"
            f"<code>{html_escape(key)}</code>\n\n"
            f"Нажмите на ключ чтобы скопировать — или откройте в Happ кнопкой ниже.",
            parse_mode="HTML",
            reply_markup=happ_keyboard(key, new_uuid, new_server["name"]),
        )

        await apply_servers(server_name)
        await apply_servers(current_server)

    elif query.data == "key":
        user = get_user(tg_id)

        if user is None:
            server = get_best_server()
            if server is None:
                await query.edit_message_text("❌ Нет свободных серверов")
                return

            user_uuid = str(uuid_lib.uuid4())
            expires = now + 7 * 24 * 3600
            add_or_update_user(
                tg_id,
                user_uuid,
                expires,
                server=server["name"],
            )
            await apply_servers(server["name"])
            user = get_user(tg_id)
            user_uuid = user[0]
            expires = user[1]
            server = next(
                (s for s in SERVERS if s["name"] == user[3]),
                server,
            )
            status = "🎁 Вам выдано 7 дней бесплатно"
        else:
            user_uuid = user[0]
            expires = user[1]
            server_name = user[3]

            if expires < now:
                await query.edit_message_text(
                    "❌ Подписка закончилась\n\n"
                    "Пополните подписку в разделе «Мой аккаунт»",
                    reply_markup=back_button(),
                )
                return

            server = next((s for s in SERVERS if s["name"] == server_name), None)
            if server is None:
                await query.edit_message_text("❌ Сервер не найден")
                return
            status = "✅ Подписка активна"

        seconds_left = expires - now
        days_left = max(0, math.ceil(seconds_left / 86400))
        vless = generate_vless(user_uuid, server)

        await query.edit_message_text(
            f"{status}\n\n"
            f"⏳ Осталось дней: {days_left}\n\n"
            f"🔑 Ваш ключ:\n\n"
            f"<code>{html_escape(vless)}</code>",
            parse_mode="HTML",
            reply_markup=happ_keyboard(vless, user_uuid, server["name"]),
        )

    elif query.data == "ref":
        ref_link = f"https://t.me/{BOT_USERNAME}?start=ref-{tg_id}"
        web_ref = f"{WEB_URL}/?ref={tg_id}"
        text = (
            "🔗 **Твои реферальные ссылки**\n\n"
            "📱 **Для бота:**\n"
            f"`{ref_link}`\n\n"
            "🌐 **Для сайта:**\n"
            f"`{web_ref}`\n\n"
            "🎁 **Как это работает:**\n"
            "• Отправь ссылку другу\n"
            "• Он переходит по ссылке\n"
            "• Ты получаешь **+5 дней** подписки\n\n"
            "👇 Нажми на ссылку, чтобы скопировать"
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔗 Скопировать ссылку бота",
                        callback_data="copy_bot_ref",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🌐 Скопировать ссылку сайта",
                        callback_data="copy_web_ref",
                    )
                ],
                [InlineKeyboardButton("⬅ Назад", callback_data="back")],
            ]
        )
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")

    elif query.data == "copy_bot_ref":
        ref_link = f"https://t.me/{BOT_USERNAME}?start=ref-{tg_id}"
        await query.answer(f"Ссылка скопирована: {ref_link}", show_alert=True)

    elif query.data == "copy_web_ref":
        web_app_url = f"{WEB_URL}/?ref={tg_id}"
        await query.answer(f"Ссылка скопирована: {web_app_url}", show_alert=True)

    elif query.data == "bonus":
        user = get_user(tg_id)
        if not user:
            await query.message.reply_text("❌ Сначала получите VPN-ключ")
            return
        uuid, expires_at, bonus_used, server = user
        if bonus_used:
            await query.message.reply_text("❌ Бонус уже был использован")
            return
        subscribed = await is_subscribed(context.bot, tg_id)
        if not subscribed:
            await query.message.reply_text(
                "🎁 Бонус за подписку\n\n"
                "Подпишитесь на наш канал:\n"
                f"{CHANNEL}\n\n"
                "После подписки нажмите кнопку ещё раз 👇"
            )
            return
        add_time(tg_id, 7)
        await apply_servers(server)
        set_bonus_used(tg_id)
        await query.message.reply_text(
            "🎉 Бонус активирован!\n\n⏳ +7 дней добавлено к подписке ✅"
        )

    elif query.data == "account":
        user = get_user(tg_id)
        if user is None:
            await query.edit_message_text(
                "У вас нет подписки", reply_markup=back_button()
            )
            return
        user_uuid, expires, bonus_used, server = user
        seconds_left = expires - now
        days_left = max(0, math.ceil(seconds_left / 86400))
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("💳 Пополнить", callback_data="pay")],
                [InlineKeyboardButton("⬅ Назад", callback_data="back")],
            ]
        )
        await query.edit_message_text(
            f"👤 *Мой аккаунт*\n\n⏳ Осталось дней: {days_left}",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    elif query.data == "pay":
        keyboard = [
            [InlineKeyboardButton("🏦 СБП", callback_data="pay_sbp")],
            [InlineKeyboardButton("💳 Crypto (USDT)", callback_data="pay_crypto")],
            [InlineKeyboardButton("⭐ Telegram Stars", callback_data="pay_stars")],
            [InlineKeyboardButton("⬅️Назад", callback_data="back")],
        ]
        await query.message.edit_text(
            "Выберите способ оплаты:\n\n"
            "Оплачивая, вы принимаете условия сервиса.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif query.data == "pay_sbp":
        keyboard = [
            [InlineKeyboardButton("1 месяц — 100 ₽", callback_data="sbp_1m")],
            [InlineKeyboardButton("3 месяца — 250 ₽", callback_data="sbp_3m")],
            [InlineKeyboardButton("12 месяцев — 1000 ₽", callback_data="sbp_12m")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="pay")],
        ]
        await query.message.edit_text(
            "Выберите тариф (СБП):",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif query.data.startswith("sbp_"):
        plan = query.data.split("_", 1)[1]
        tariff = SBP_TARIFFS.get(plan)
        if not tariff:
            await query.answer("Неизвестный тариф")
            return
        username = query.from_user.username or ""
        try:
            tx = await create_sbp_payment(tg_id, plan, username=f"@{username}" if username else "")
        except Exception as e:
            await query.message.edit_text(
                f"Не удалось создать платёж. Попробуйте позже.\n\n{e}",
                reply_markup=back_button(),
            )
            return
        redirect = pick(tx, "redirect")
        if not redirect:
            await query.message.edit_text(
                "Не удалось получить ссылку на оплату.",
                reply_markup=back_button(),
            )
            return
        keyboard = [[InlineKeyboardButton("🏦 Оплатить СБП", url=redirect)]]
        await query.message.edit_text(
            f"Тариф: {tariff['title']}\nЦена: {tariff['price']} ₽\n\n"
            "После оплаты доступ будет выдан автоматически.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif query.data == "pay_crypto":
        keyboard = [
            [InlineKeyboardButton("1 месяц — 1 USDT", callback_data="buy_1m")],
            [InlineKeyboardButton("3 месяца — 2.5 USDT", callback_data="buy_3m")],
            [InlineKeyboardButton("12 месяцев — 10 USDT", callback_data="buy_12m")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back")],
        ]
        await query.message.edit_text(
            "Выберите тариф:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif query.data.startswith("buy_"):
        plan = query.data.split("_")[1]
        tariff = TARIFFS[plan]
        invoice = await crypto.create_invoice(
            asset="USDT",
            amount=tariff["price"],
            description=f"{tg_id}|{plan}",
        )
        keyboard = [[InlineKeyboardButton("💳 Оплатить", url=invoice.bot_invoice_url)]]
        await query.message.edit_text(
            f"Тариф: {tariff['title']}\nЦена: {tariff['price']} USDT\n\n"
            "После оплаты доступ будет выдан автоматически.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif query.data == "pay_stars":
        keyboard = [
            [InlineKeyboardButton("⭐ 1 месяц - 80", callback_data="stars_1m")],
            [InlineKeyboardButton("⭐ 3 месяца — 200", callback_data="stars_3m")],
            [InlineKeyboardButton("⭐ 12 месяцев — 800", callback_data="stars_12m")],
            [InlineKeyboardButton("⬅️Назад", callback_data="back")],
        ]
        await query.message.edit_text(
            "Выберите тариф (Telegram Stars):",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif query.data.startswith("stars_"):
        plan = query.data.split("_")[1]
        tariff = STARS_TARIFFS[plan]
        await context.bot.send_invoice(
            chat_id=query.from_user.id,
            title=f"VPN {tariff['title']}",
            description="Доступ к VPN",
            payload=f"stars|{plan}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice("VPN доступ", tariff["stars"])],
        )


async def check_sbp_payments(application):
    while True:
        try:
            await check_pending_sbp_payments(apply_servers)
        except Exception as e:
            print("SBP LOOP ERROR:", e, flush=True)
        await asyncio.sleep(15)


async def check_crypto_payments(application):
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
                    await application.bot.send_message(
                        tg_id,
                        f"✅ Оплата получена!\nВам начислено {tariff['days']} дней.",
                    )
                    await crypto.delete_invoice(inv.invoice_id)
                except Exception as e:
                    print("CRYPTO NOTIFY ERROR:", e)
        except Exception as e:
            print("CRYPTO LOOP ERROR:", e)
        await asyncio.sleep(30)


async def post_init(application):
    asyncio.create_task(check_crypto_payments(application))
    asyncio.create_task(check_sbp_payments(application))


async def send_legal_message(message, text):
    chunks = split_legal(text)
    for chunk in chunks:
        await message.reply_text(chunk)


async def link_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    tg_username = update.effective_user.username
    if not context.args:
        await update.message.reply_text(
            "Привязка сайта к Telegram\n\n"
            "1. Зарегистрируйтесь на сайте\n"
            f"2. Откройте «Аккаунт» → получите код\n"
            "3. Отправьте сюда: /link КОД\n\n"
            f"Сайт: {WEB_URL}"
        )
        return
    code = context.args[0]
    result_id, error = consume_link_code(code, tg_id, tg_username)
    if error:
        await update.message.reply_text(f"❌ {error}")
        return
    if tg_username:
        update_user_username(result_id, tg_username)
    user = get_user(result_id)
    if user:
        await apply_servers(user[3])
    await update.message.reply_text(
        "✅ Telegram привязан к аккаунту сайта.\n"
        "Войдите на сайте ещё раз тем же логином — подписка общая."
    )


async def terms_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_legal_message(update.message, TERMS_TEXT)


async def privacy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_legal_message(update.message, PRIVACY_TEXT)


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    if payload.startswith("stars|"):
        plan = payload.split("|")[1]
        tariff = STARS_TARIFFS[plan]
        tg_id = update.effective_user.id
        add_time(tg_id, tariff["days"])
        user = get_user(tg_id)
        if user:
            await apply_servers(user[3])
        await update.message.reply_text(
            f"✅ Оплата получена!\nНачислено {tariff['days']} дней."
        )


def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("link", link_cmd))
    app.add_handler(CommandHandler("terms", terms_cmd))
    app.add_handler(CommandHandler("privacy", privacy_cmd))
    app.add_handler(CommandHandler("adddays", adddays))
    app.add_handler(CommandHandler("time", check_time))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    print("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
