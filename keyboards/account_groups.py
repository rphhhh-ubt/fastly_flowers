from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import types


def grantes_menu_keyboard(prefix="grantes_"):
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="➕ Создать группу", callback_data=f"grantes_create")],
        [types.InlineKeyboardButton(text="✏️ Редактировать группу", callback_data=f"grantes_edit")],
        [types.InlineKeyboardButton(text="🗑️ Удалить группу", callback_data=f"grantes_delete")],
        [types.InlineKeyboardButton(text="📃 Доступные группы", callback_data=f"grantes_list")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_accounts")],
    ])
