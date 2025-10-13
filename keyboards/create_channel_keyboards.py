from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def build_create_channel_keyboard(accounts, selected_ids=None):
    if selected_ids is None:
        selected_ids = []

    keyboard = []

    for acc in accounts:
        acc_id = acc["id"]
        username = acc.get("username") or ''
        first_name = acc.get("first_name") or ''
        last_name = acc.get("last_name") or ''
        is_selected = "✅" if acc_id in selected_ids else "☑️"
        button_text = f"{is_selected} {username} | {first_name} {last_name}".strip()
        keyboard.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"create_channel_toggle_{acc_id}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(text="✅ Все", callback_data="create_channel_select_all"),
        InlineKeyboardButton(text="➡️ Далее", callback_data="proceed_create_channel")
        
    ])
    keyboard.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="show_create_task_menu")
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)
