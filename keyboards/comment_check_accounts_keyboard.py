# keyboards/comment_check_accounts_keyboard.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Dict, Any


def cchk_accounts_keyboard(
    accounts: List[Dict[str, Any]],
    selected_ids: set[int] | list[int] | None = None,
    page: int = 0,
    per_page: int = 10,
    groups: List[Dict[str, Any]] | None = None,
) -> InlineKeyboardMarkup:
    if selected_ids is None:
        selected_ids = set()
    else:
        selected_ids = set(selected_ids)

    start = page * per_page
    chunk = accounts[start:start + per_page]

    rows: list[list[InlineKeyboardButton]] = []

    # строки с аккаунтами
    for acc in chunk:
        acc_id = acc["id"]
        uname = acc.get("username") or "-"
        phone = acc.get("phone") or "-"
        mark = "✅" if acc_id in selected_ids else "⏹️"
        txt = f"{mark} {acc_id} ▸ @{uname} ▸ {phone}"
        rows.append([InlineKeyboardButton(text=txt, callback_data=f"cchk_toggle:{acc_id}")])

    # пагинация
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"cchk_page:{page-1}"))
    if start + per_page < len(accounts):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"cchk_page:{page+1}"))
    if nav:
        rows.append(nav)

    # чипсы групп
    chips: list[InlineKeyboardButton] = []
    if groups:
        for g in groups:
            cnt = int(g.get("count") or 0)
            if cnt < 1:
                continue
            name = f"{g.get('emoji', '')} {g.get('name', '')}".strip()
            label = f"{name} ({cnt})"
            chips.append(InlineKeyboardButton(text=label, callback_data=f"cchk_group:{g['id']}"))
    for i in range(0, len(chips), 3):
        rows.append(chips[i:i+3])

    # массовые действия
    rows.append([
        InlineKeyboardButton(text="Выбрать все", callback_data="cchk_select_all"),
        InlineKeyboardButton(text="Снять все",   callback_data="cchk_clear_all"),
    ])
    rows.append([
        InlineKeyboardButton(text="Далее ➜", callback_data="cchk_proceed"),
        InlineKeyboardButton(text="Отмена",   callback_data="menu_main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
