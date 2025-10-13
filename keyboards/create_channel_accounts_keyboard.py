# keyboards/create_channel_accounts_keyboard.py
from typing import List, Dict, Any, Iterable, Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def create_channel_accounts_keyboard(
    accounts: List[Dict[str, Any]],
    selected: Iterable[int] | None,
    page: int = 0,
    per_page: int = 10,
    groups: Optional[List[Dict[str, Any]]] = None,  # [{'id','name','emoji','count'}, ...]
) -> InlineKeyboardMarkup:
    selected = set(selected or [])
    total = len(accounts)
    start = page * per_page
    chunk = accounts[start : start + per_page]

    rows: list[list[InlineKeyboardButton]] = []

    # список аккаунтов (текущая страница)
    for acc in chunk:
        acc_id = acc["id"]
        uname  = acc.get("username") or "-"
        if uname != "-" and not str(uname).startswith("@"):
            uname = f"@{uname}"
        phone  = acc.get("phone") or "-"
        mark   = "✅" if acc_id in selected else "⏹️"
        txt    = f"{mark} {acc_id} ▸ {uname} ▸ {phone}"
        rows.append([InlineKeyboardButton(text=txt, callback_data=f"crch_toggle:{acc_id}")])

    # навигация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"crch_page:{page-1}"))
    if start + per_page < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"crch_page:{page+1}"))
    if nav:
        rows.append(nav)

    # чипсы групп (по 3 в ряд). показываем только с count >= 1
    chips: list[InlineKeyboardButton] = []
    if groups:
        for g in groups:
            cnt = int(g.get("count") or 0)
            if cnt < 1:
                continue
            name = f"{g.get('emoji','')} {g.get('name','')}".strip()
            label = f"{name} ({cnt})"
            chips.append(InlineKeyboardButton(text=label, callback_data=f"crch_group:{g['id']}"))

    for i in range(0, len(chips), 3):
        rows.append(chips[i:i+3])

    # массовые действия
    rows.append([
        InlineKeyboardButton(text="✅ Выбрать все", callback_data="crch_select_all"),
        InlineKeyboardButton(text="⏹️ Снять все",   callback_data="crch_clear_all"),
    ])

    rows.append([
        InlineKeyboardButton(text="➡ Далее", callback_data="crch_next"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="menu_main"),
    ])


    return InlineKeyboardMarkup(inline_keyboard=rows)
