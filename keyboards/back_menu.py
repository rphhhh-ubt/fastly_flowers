from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def back_to_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="menu_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def back_to_accounts_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                text="⬅️ Назад к списку аккаунтов",
                callback_data="accounts_list"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)