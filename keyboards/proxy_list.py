from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.db import count_accounts_using_proxy

def proxy_list_keyboard(proxies):
    keyboard = []
    for proxy in proxies:
        proxy_id = proxy["id"]
        host = proxy["host"]
        port = proxy["port"]
        username = proxy.get("username")
        password = proxy.get("password")
        status = proxy.get("status", "unknown")

        accounts_count = count_accounts_using_proxy(host, port, username, password)

        # Выбираем значок статуса
        if status == "working":
            status_emoji = "✅"
        elif status == "bad":
            status_emoji = "❌"
        else:
            status_emoji = "❔"

        label = f"{host}:{port} ({accounts_count} акк) {status_emoji}"

        keyboard.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"check_proxylist_{proxy_id}"
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=f"confirm_delete_proxy_{proxy_id}"
            )
        ])

    if proxies:
        keyboard.append([
            InlineKeyboardButton(text="✅ Проверить все", callback_data="check_all_proxies"),
            InlineKeyboardButton(text="🗑 Удалить плохие", callback_data="confirm_delete_bad_proxies"),
        ])

    keyboard.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_proxies")
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)
