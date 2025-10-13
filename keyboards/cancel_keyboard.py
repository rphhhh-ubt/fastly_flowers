from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_to_main_menu")]
    ])
