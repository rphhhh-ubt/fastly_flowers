# keyboards/back_to_proxies_menu.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def back_to_proxies_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_proxies")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
