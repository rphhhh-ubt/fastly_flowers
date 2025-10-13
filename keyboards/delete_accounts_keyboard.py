# keyboards/delete_accounts_keyboard.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def delete_accounts_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(text="❌ Удалить невалидные аккаунты", callback_data="delete_invalid_accounts"),
        ],
        [
            InlineKeyboardButton(text="🗑️ Выбрать аккаунты для удаления", callback_data="select_accounts_to_delete"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_accounts"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
