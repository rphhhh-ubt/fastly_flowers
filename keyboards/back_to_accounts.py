# keyboards/back_to_accounts.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def back_to_accounts_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="⬅️ Назад к списку аккаунтов", callback_data="accounts_list")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
