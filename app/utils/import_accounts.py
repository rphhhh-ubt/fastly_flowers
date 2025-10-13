# app/utils/import_accounts.py

import os
import re
import json
import zipfile
import asyncio
from aiogram.types import BufferedInputFile
from app.db import (
    create_account_with_metadata,
    is_account_exists,
    get_available_api_key,
    increment_api_key_usage,
    proxy_exists,
    save_proxy,
    ensure_accounts_metadata_columns,
    account_exists_by_session,
    get_account_by_session_string, 
    merge_account_metadata_by_session,
)
from app.db_bootstrap import bootstrap_accounts_privileges  # <<< добавили
from telethon import TelegramClient
from telethon.sessions import SQLiteSession, StringSession
import socks

print("[IMPORT ACCOUNTS] loaded from:", __file__, flush=True)



def _find_json_for_session(session_file: str, temp_dir: str) -> str | None:
    """
    Пытается сопоставить .session с .json:
    - <stem>.json
    - <stem без суффиксов _telethon/_tdesktop/_td/_tdata>.json
    - <часть до первого _>.json
    - <числовой префикс>.json (если есть)
    Возвращает первый найденный путь или None.
    """
    stem = session_file[:-8]  # убрать ".session"
    candidates = [os.path.join(temp_dir, stem + ".json")]

    # убрать распространённые суффиксы
    for suf in ("_telethon", "_tdesktop", "_td", "_tdata"):
        if stem.endswith(suf):
            candidates.append(os.path.join(temp_dir, stem[:-len(suf)] + ".json"))

    # до первого подчёркивания
    if "_" in stem:
        candidates.append(os.path.join(temp_dir, stem.split("_", 1)[0] + ".json"))

    # числовой префикс
    m = re.match(r"(\d{6,})", stem)
    if m:
        candidates.append(os.path.join(temp_dir, m.group(1) + ".json"))

    # удалить дубликаты, вернуть первый существующий
    seen = set()
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        if os.path.exists(p):
            return p
    return None


# --- helpers for JSON meta parsing and logging ---
def _safe_int(v):
    try:
        if v is None or v == "":
            return None
        return int(v)
    except Exception:
        return None

def _safe_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes", "y", "on"):
            return True
        if s in ("false", "0", "no", "n", "off"):
            return False
    return False

def _safe_str(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None

def _load_json_metadata(json_path: str) -> dict:
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        if not raw:
            return {}
        data = json.loads(raw)
        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, dict):
            return {}
        meta = {
            "device_model":     _safe_str(data.get("device")),
            "system_version":   _safe_str(data.get("sdk")),
            "app_version":      _safe_str(data.get("app_version")),
            "lang_code":        _safe_str(data.get("lang_code")),
            "system_lang_code": _safe_str(data.get("system_lang_code")),
            "is_premium":       _safe_bool(data.get("is_premium")),
            "register_time":    _safe_int(data.get("register_time")),
        }
        cleaned = {}
        for k, v in meta.items():
            if k == "is_premium":
                cleaned[k] = bool(v)
            elif v is not None:
                cleaned[k] = v
        return cleaned
    except Exception as e:
        print(f"[IMPORT] meta parse error: {e}", flush=True)
        return {}

def _print_meta_loaded(index: int, meta: dict):
    if not meta:
        print(f"[IMPORT] [{index}] meta: none", flush=True)
        return
    order = ["device_model", "system_version", "app_version", "lang_code", "system_lang_code", "is_premium", "register_time"]
    parts = []
    for k in order:
        if k in meta:
            v = meta[k]
            parts.append(f"{k}={v}{' (unix)' if k=='register_time' and v is not None else ''}")
    print(f"[IMPORT] [{index}] meta: {', '.join(parts) if parts else 'none'}", flush=True)


async def _extract_zip(zip_path: str, temp_dir: str):
    def _extract():
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(temp_dir)
    await asyncio.to_thread(_extract)

def _read_proxies_file(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return [line.strip() for line in f if line.strip()]

def _sqlite_file_to_string_session(session_path: str) -> str:
    base = session_path[:-8] if session_path.endswith(".session") else session_path
    sqlite_session = SQLiteSession(base)
    return StringSession.save(sqlite_session)

def _make_proxy_tuple(host, port, user, pwd):
    return (socks.SOCKS5, host, int(port), True, user or None, pwd or None)


async def _import_one(index: int, session_file: str, proxy_line: str, temp_dir: str, log, counters):
    session_path = os.path.join(temp_dir, session_file)
    json_path = _find_json_for_session(session_file, temp_dir)
    print(f"[IMPORT] [{index}] session={session_file}, json={'found: ' + os.path.basename(json_path) if json_path else 'none'}", flush=True)

    
    # 1) proxy
    try:
        parts = (proxy_line or "").split(":")
        phost = parts[0]
        pport = int(parts[1])
        puser = parts[2] if len(parts) > 2 and parts[2] else None
        ppwd  = parts[3] if len(parts) > 3 and parts[3] else None
    except Exception as e:
        msg = f"[❌] {session_file} — неверный формат прокси '{proxy_line}': {e}"
        print(f"[IMPORT] {msg}", flush=True); counters["fail"] += 1; log.append(msg); return

    # 2) api key
    api_key = get_available_api_key()
    if not api_key:
        msg = f"[❌] {session_file} — нет свободных API-ключей"
        print(f"[IMPORT] {msg}", flush=True); counters["fail"] += 1; log.append(msg); return

    # 3) .session → StringSession
    try:
        string_sess = _sqlite_file_to_string_session(session_path)
        print(f"[IMPORT] [{index}] StringSession получен ({len(string_sess)} символов)", flush=True)
    except Exception as e:
        msg = f"[❌] {session_file} — не удалось прочитать .session: {e}"
        print(f"[IMPORT] {msg}", flush=True); counters["fail"] += 1; log.append(msg); return
    

    # === НОВОЕ: если такой session уже есть — «доклеим» МЕТА из найденного JSON и выйдем
    if account_exists_by_session(string_sess):
        if json_path:
            meta = _load_json_metadata(json_path) or {}
            try:
                acc = get_account_by_session_string(string_sess) or {}
                if not meta:
                    msg = f"[ℹ️] аккаунт ID {acc.get('id','?')}: JSON найден, но метаданных нет — обновлять нечего"
                    counters["skipped"] += 1
                else:
                    affected = merge_account_metadata_by_session(string_sess, meta)
                    if affected:
                        msg = f"[ℹ️] метаданные для аккаунта ID {acc.get('id','?')} обновлены (только пустые поля)"
                    else:
                        msg = f"[ℹ️] аккаунт ID {acc.get('id','?')} уже содержит все поля, обновлять нечего"
                    counters["updated"] += 1   # ← а не fail
            except Exception as e:
                msg = f"[⚠️] не удалось обновить метаданные для дубликата: {e}"
                counters["fail"] += 1         # ← это уже ошибка
        else:
            msg = f"[ℹ️] найден дубликат по session_string, подходящий JSON не обнаружен — пропуск"
            counters["skipped"] += 1          # ← пропуск, не ошибка

        log.append(msg)
        print(f"[IMPORT] {msg}", flush=True)
        return

    
    
    proxy_tuple = _make_proxy_tuple(phost, pport, puser, ppwd)
    print(f"[IMPORT] [{index}] proxy={phost}:{pport} user={'yes' if puser else 'no'}", flush=True)

    # 4) connect & validate
    client = None
    try:
        client = TelegramClient(
            StringSession(string_sess),
            api_key["api_id"],
            api_key["api_hash"],
            proxy=proxy_tuple,
            connection_retries=1,
            request_retries=1,
            timeout=20,
        )
        await client.connect()
        print(f"[IMPORT] [{index}] connected", flush=True)
        increment_api_key_usage(api_key["id"])

        me = await client.get_me()
        if not me:
            raise Exception("Сессия не авторизована (get_me вернул None)")

        phone = getattr(me, "phone", None)
        username = getattr(me, "username", None)
        who = phone or username or session_file
        print(f"[IMPORT] [{index}] me: phone={phone} username={username}", flush=True)

        if is_account_exists(phone, username):
            msg = f"[ℹ️] {who} — уже существует (по phone/username), пропуск"
            counters["fail"] += 1; log.append(msg); print(f"[IMPORT] {msg}", flush=True); return

        # 5) save proxy (if new)
        if phost and pport and not proxy_exists(phost, pport, puser, ppwd):
            save_proxy(phost, pport, puser, ppwd)

        # 6) meta from JSON
        meta = _load_json_metadata(json_path) if json_path else {}
        _print_meta_loaded(index, meta)


        # 7) save account
        create_account_with_metadata(
            session_string=string_sess,
            proxy_type="socks5",
            proxy_host=phost,
            proxy_port=pport,
            proxy_username=puser,
            proxy_password=ppwd,
            phone=phone,
            username=username,
            device_model=meta.get("device_model"),
            system_version=meta.get("system_version"),
            app_version=meta.get("app_version"),
            lang_code=meta.get("lang_code"),
            system_lang_code=meta.get("system_lang_code"),
            is_premium=bool(meta.get("is_premium", False)),
            register_time=meta.get("register_time"),
        )

        msg = f"[✅] {who} — импортирован"
        counters["ok"] += 1; log.append(msg); print(f"[IMPORT] {msg}", flush=True)

    except Exception as e:
        msg = f"[❌] {session_file} — ошибка: {e}"
        counters["fail"] += 1; log.append(msg); print(f"[IMPORT] {msg}", flush=True)
    finally:
        if client:
            try: await client.disconnect()
            except Exception: pass


async def import_accounts_from_zip(message, zip_path, temp_dir):
    print(f"[IMPORT] start zip_path={zip_path} temp_dir={temp_dir}", flush=True)

    # 0) Авто-ensure + авто-BOOTSTRAP при ошибке прав
    try:
        ensure_accounts_metadata_columns()
        print("[IMPORT] ensure_accounts_metadata_columns: OK", flush=True)
    except Exception as e:
        print(f"[IMPORT] ensure failed: {e} — trying bootstrap...", flush=True)
        res = bootstrap_accounts_privileges()
        print(f"[BOOTSTRAP] result: {res}", flush=True)
        # повторим ensure
        try:
            ensure_accounts_metadata_columns()
            print("[IMPORT] ensure_accounts_metadata_columns after bootstrap: OK", flush=True)
        except Exception as e2:
            print(f"[IMPORT] ❌ ensure failed again: {e2}", flush=True)
            await message.answer("❌ Ошибка при подготовке базы данных.")
            return

    log, counters = [], {"ok": 0, "updated": 0, "skipped": 0, "fail": 0}
    try:
        # 1) unzip
        await _extract_zip(zip_path, temp_dir)
        print("[IMPORT] zip extracted", flush=True)

        # 2) list .session only
        sessions = [f for f in os.listdir(temp_dir) if f.endswith(".session")]
        sessions.sort()
        proxies_path = os.path.join(temp_dir, "proxies.txt")
        proxy_lines = _read_proxies_file(proxies_path)
        print(f"[IMPORT] found sessions: {len(sessions)}; proxies lines: {len(proxy_lines)} (json files not counted)", flush=True)

        if len(proxy_lines) != len(sessions):
            await message.answer("❌ Количество прокси не совпадает с количеством сессий.")
            return

        # 3) import
        for i, sess in enumerate(sessions, 1):
            await _import_one(i, sess, proxy_lines[i - 1], temp_dir, log, counters)

        # 4) send log
        log_text = (
            "\n".join(log) +
            f"\n\nИтого:\n"
            f"✅ Импортировано: {counters['ok']}\n"
            f"♻️ Обновлено метаданных: {counters['updated']}\n"
            f"⏭️ Пропущено: {counters['skipped']}\n"
            f"❌ Ошибок: {counters['fail']}"
        )
        log_file_path = os.path.join(temp_dir, "import_log.txt")
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(log_text)

        with open(log_file_path, "rb") as f:
            await message.answer_document(
                document=BufferedInputFile(f.read(), filename="import_log.txt"),
                caption="📄 Лог импорта аккаунтов"
            )

    except Exception as e:
        print(f"❌ Критическая ошибка в import_accounts_from_zip: {e}", flush=True)
        import traceback; traceback.print_exc()
        await message.answer("❌ Произошла ошибка при обработке архива.")
    finally:
        # cleanup
        try:
            if os.path.exists(zip_path): os.remove(zip_path)
            if os.path.exists(temp_dir):
                for f in os.listdir(temp_dir):
                    try: os.remove(os.path.join(temp_dir, f))
                    except Exception: pass
                try: os.rmdir(temp_dir)
                except Exception: pass
        except Exception:
            pass
