# BushVPN

VPN-сервис: Telegram-бот, личный кабинет и автоматическая выдача ключей **VLESS + Reality** (sing-box). Клиент — Happ.

Новому пользователю даётся 7 дней. Дальше подписка, рефералы и смена сервера. Ноды обновляются сами по SSH.

```text
пользователь → бот / кабинет → sqlite → sync_worker → ноды
```

## Возможности

- пробные 7 дней при `/start`
- ключ и кнопка «Подключить в Happ»
- смена сервера, индикатор нагрузки
- бонус +7 дней за подписку на канал
- реферал: +5 дней пригласившему
- кабинет: регистрация, ключ, оплата, привязка Telegram
- оплата: CryptoBot, СБП (Platega), звёзды Telegram

## Запуск

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp config.example.py config.py
cp servers.example.py servers.py
cp -r templates.example templates
```

Заполни `config.py`, `servers.py` и Reality `private_key` в `templates/*.json`.

```bash
python3 bot.py
python3 sync_worker.py
cd webpanel && uvicorn app:app --host 127.0.0.1 --port 8080
```

Импорт Happ (по желанию):

```bash
cd happ_import && uvicorn app:app --host 127.0.0.1 --port 8090
```

## Команды бота

```text
/start              меню и пробный доступ
/link <код>         привязка к кабинету
/terms  /privacy    документы
/adddays <id> <n>   продлить подписку (админ)
/time <id>          срок подписки (админ)
```

## Процессы

| сервис | команда |
| --- | --- |
| бот | `python3 bot.py` |
| кабинет | `cd webpanel && uvicorn app:app --host 127.0.0.1 --port 8080` |
| синк нод | `python3 sync_worker.py` |
| Happ | `cd happ_import && uvicorn app:app --host 127.0.0.1 --port 8090` |
| напоминания | `python3 notify_expiring.py` |
| полный ресинк | `python3 restore_all.py` |

`config.py`, `servers.py`, `templates/`, базы и логи в репозиторий не входят.
