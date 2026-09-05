import asyncio
from telegram import Bot
from db import get_users_for_warning, mark_notified
from config import BOT_TOKEN

bot = Bot(token=BOT_TOKEN)

async def main():
    users = get_users_for_warning()

    for tg_id, expires_at in users:
        try:
            await bot.send_message(
                chat_id=tg_id,
                text=(
                    "⚠️ Ваша подписка BushVPN заканчивается завтра\n\n"
                    "Чтобы не потерять доступ, продлите подписку заранее 💳"
                )
            )
            mark_notified(tg_id)
        except Exception as e:
            print(f"Failed to notify {tg_id}: {e}")

asyncio.run(main())
