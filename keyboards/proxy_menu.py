# keyboards/proxy_menu.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def proxy_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(text="➕ Импортировать прокси", callback_data="import_proxies"),
            InlineKeyboardButton(text="📋 Просмотреть прокси", callback_data="view_proxies"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
