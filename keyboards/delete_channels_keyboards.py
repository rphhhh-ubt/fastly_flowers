from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def delete_channels_select_accounts_keyboard(accounts, selected_ids=None):
    selected_ids = selected_ids or []

    keyboard = []
    for acc in accounts:
        checked = "✅" if acc["id"] in selected_ids else "☐"
        label = acc.get("username") or acc.get("label") or f"ID {acc['id']}"
        text = f"{checked} {label}"
        keyboard.append([
            InlineKeyboardButton(text=text, callback_data=f"toggle_account_{acc['id']}")
        ])

    keyboard.append([
        InlineKeyboardButton(text="✅ Выбрать всех", callback_data="select_all_accounts"),
        InlineKeyboardButton(text="➡️ Далее", callback_data="proceed_delete_channels"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)
