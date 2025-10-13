import psycopg2, json, os
from psycopg2.extras import RealDictCursor, Json
from datetime import datetime, timezone
from contextlib import contextmanager
from dotenv import load_dotenv
load_dotenv()
from typing import List, Dict, Any

from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


def _req(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v

def _build_db_config() -> dict:
    """
    Собираем параметры БД из окружения.
    Поддерживаем 2 варианта:
      1) DATABASE_URL=postgresql://user:pass@host:5432/dbname
         -> вернём {"dsn": "..."} (psycopg2.connect(**DB_CONFIG) продолжит работать)
      2) Компонентами: DB_NAME, DB_USER, DB_PASSWORD, (DB_HOST, DB_PORT)
    """
    dsn = os.getenv("DATABASE_URL", "").strip()
    if dsn:
        return {"dsn": dsn}

    # компонентный вариант
    return {
        "dbname": _req("DB_NAME"),
        "user": _req("DB_USER"),
        "password": _req("DB_PASSWORD"),
        "host": os.getenv("DB_HOST", "127.0.0.1").strip() or "127.0.0.1",
        "port": int(os.getenv("DB_PORT", "5432") or "5432"),
    }

# <<< это и есть единственный источник правды для всех legacy-вызовов >>>
DB_CONFIG = _build_db_config()



def get_connection(): 
    return psycopg2.connect(**DB_CONFIG) 
def get_db_connection(): 
    return psycopg2.connect(**DB_CONFIG) 
def get_conn(): 
    # алиас для совместимости со вставками twofa 
    return get_connection()

def get_all_accounts():
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM accounts;")
    result = cur.fetchall()
    cur.close()
    conn.close()
    return result

def get_account_by_id(account_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM accounts WHERE id = %s;", (account_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result

def get_available_api_key():
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT * FROM api_keys
        WHERE requests_today < daily_limit
        ORDER BY requests_today ASC
        LIMIT 1
    """)
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result

def increment_api_key_usage(api_key_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE api_keys
        SET requests_today = requests_today + 1
        WHERE id = %s
    """, (api_key_id,))
    conn.commit()
    cur.close()
    conn.close()

def update_task_status(task_id: int, status: str, result: str = None):
    conn = get_connection()
    try:
        cur = conn.cursor()
        if result is not None:
            cur.execute("""
                UPDATE tasks
                SET status = %s,
                    result = %s,
                    updated_at = now()
                WHERE id = %s;
            """, (status, result, task_id))
        else:
            cur.execute("""
                UPDATE tasks
                SET status = %s,
                    updated_at = now()
                WHERE id = %s;
            """, (status, task_id))

        if status == 'error' and result:
            log_action(
                action='task_error',
                description=result[:500],
                task_id=task_id
            )

        conn.commit()
    except Exception as e:
        print(f"[❌ update_task_status] Ошибка: {e}")
        conn.rollback()
    finally:
        if cur:
            cur.close()
        conn.close()




def save_channel(account_id, title, username, invite_link, is_public, avatar_path=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO channels (account_id, title, username, invite_link, is_public, avatar_path)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
    """, (account_id, title, username, invite_link, is_public, avatar_path))
    channel_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return channel_id

def update_channel_invite(username, invite_link):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE channels
        SET invite_link = %s,
            is_public = FALSE
        WHERE username = %s;
    """, (invite_link, username))
    conn.commit()
    cur.close()
    conn.close()

def channel_exists(channel_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM channels WHERE id = %s", (channel_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result is not None

def delete_channel_by_title(account_id, title):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM channels
        WHERE account_id = %s AND title = %s
    """, (account_id, title))
    conn.commit()
    cur.close()
    conn.close()

def add_task(account_id, task_type, payload, scheduled_at=None, is_master=False, parent_id=None):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO tasks (account_id, type, payload, scheduled_at, is_master, parent_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
    """, (
        account_id,
        task_type,
        json.dumps(payload),
        scheduled_at,
        is_master,
        parent_id
    ))

    task_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return task_id

def delete_task(task_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM tasks WHERE id = %s;", (task_id,))
    conn.commit()
    cur.close()
    conn.close()

def update_task(task_id, updates: dict):
    conn = get_connection()
    cur = conn.cursor()

    sets = []
    values = []

    for key, value in updates.items():
        sets.append(f"{key} = %s")
        values.append(value)

    query = f"UPDATE tasks SET {', '.join(sets)} WHERE id = %s"
    values.append(task_id)

    cur.execute(query, values)
    conn.commit()
    cur.close()
    conn.close()

def get_pending_tasks(limit=10):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT * FROM tasks
        WHERE status = 'pending'
          AND is_active = TRUE
          AND scheduled_at <= NOW()
        ORDER BY scheduled_at ASC
        LIMIT %s;
    """, (limit,))
    tasks = cur.fetchall()
    cur.close()
    conn.close()
    return tasks


def get_task_by_id(task_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM tasks WHERE id = %s;", (task_id,))
    task = cur.fetchone()
    cur.close()
    conn.close()
    return task

def delete_task_from_db(task_id):
    print(f"DELETE FROM tasks WHERE id = {task_id}")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM tasks WHERE id = %s;", (task_id,))
    conn.commit()
    cur.close()
    conn.close()

def toggle_task_active(task_id, is_active):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE tasks
        SET is_active = %s, updated_at = NOW()
        WHERE id = %s;
    """, (is_active, task_id))
    conn.commit()
    cur.close()
    conn.close()

def get_all_tasks(task_type=None):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    if task_type:
        cur.execute("""
            SELECT * FROM tasks
            WHERE type = %s
            ORDER BY created_at DESC
        """, (task_type,))
    else:
        cur.execute("""
            SELECT * FROM tasks
            ORDER BY created_at DESC
        """)

    tasks = cur.fetchall()
    cur.close()
    conn.close()
    return tasks


def get_tasks_by_status(status, limit=10, offset=0):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT * FROM tasks
        WHERE status = %s
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """, (status, limit, offset))
    tasks = cur.fetchall()
    cur.close()
    conn.close()
    return tasks

def count_all_tasks():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tasks")
    total = cur.fetchone()[0]
    cur.close()
    conn.close()
    return total

def count_tasks_by_status(status):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tasks WHERE status = %s", (status,))
    total = cur.fetchone()[0]
    cur.close()
    conn.close()
    return total

def get_tasks_by_type(task_type, limit=10, offset=0):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT * FROM tasks
        WHERE type = %s
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s;
    """, (task_type, limit, offset))
    tasks = cur.fetchall()
    cur.close()
    conn.close()
    return tasks

def count_tasks_by_type(task_type):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tasks WHERE type = %s;", (task_type,))
    total = cur.fetchone()[0]
    cur.close()
    conn.close()
    return total

def get_tasks_by_filters(filters, limit=10, offset=0):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    where_clauses = ["parent_id IS NULL"]  # показываем только главные задачи
    params = []

    if "status" in filters and filters["status"]:
        where_clauses.append("status = %s")
        params.append(filters["status"])

    if "type" in filters and filters["type"]:
        where_clauses.append("type = %s")
        params.append(filters["type"])

    where_clause = " AND ".join(where_clauses)

    query = f"""
        SELECT * FROM tasks
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    cur.execute(query, params)
    tasks = cur.fetchall()
    cur.close()
    conn.close()
    return tasks


def count_tasks_by_filters(filters):
    conn = get_connection()
    cur = conn.cursor()

    where_clauses = ["parent_id IS NULL"]  # исключаем подзадачи
    params = []

    if "status" in filters and filters["status"]:
        where_clauses.append("status = %s")
        params.append(filters["status"])

    if "type" in filters and filters["type"]:
        where_clauses.append("type = %s")
        params.append(filters["type"])

    where_clause = " AND ".join(where_clauses)

    query = f"SELECT COUNT(*) FROM tasks WHERE {where_clause}"

    cur.execute(query, params)
    total = cur.fetchone()[0]
    cur.close()
    conn.close()
    return total


def log_action(action, description=None, task_id=None, ip_address=None, user_agent=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO logs (action, description, task_id, ip_address, user_agent, timestamp)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (action, description, task_id, ip_address, user_agent, datetime.now()))
    conn.commit()
    cur.close()
    conn.close()
 
def get_all_logs(page=1, per_page=1000, only_errors=False):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    offset = (page - 1) * per_page

    base_query = "FROM logs"
    if only_errors:
        base_query += " WHERE action = 'task_error'"

    # Получение самих логов
    cur.execute(f"""
        SELECT * {base_query}
        ORDER BY timestamp DESC
        LIMIT %s OFFSET %s
    """, (per_page, offset))
    logs = cur.fetchall()

    # Подсчёт общего количества записей
    cur.execute(f"SELECT COUNT(*) {base_query}")
    total = cur.fetchone()["count"]

    cur.close()
    conn.close()

    total_pages = (total + per_page - 1) // per_page
    return logs, total_pages


def count_logs():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM logs")
    total = cur.fetchone()[0]
    cur.close()
    conn.close()
    return total


def is_account_busy(account_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM tasks
        WHERE account_id = %s AND status = 'pending' AND is_active = TRUE
    """, (account_id,))
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count > 1

def log_task_event(task_id, message, status="info", duration=None, account_id=None, proxy=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO task_logs (task_id, status, message, duration, account_id, proxy, timestamp)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
    """, (task_id, status, message, duration, account_id, proxy))
    conn.commit()
    cur.close()
    conn.close()

def get_task_logs(task_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT * FROM task_logs WHERE task_id = %s ORDER BY timestamp DESC",
        (task_id,)
    )
    logs = cur.fetchall()
    cur.close()
    conn.close()
    return logs

def check_spamblock_status(account_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT is_spam_blocked, spam_block_until FROM accounts WHERE id = %s", (account_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    if result:
        return result['is_spam_blocked'], result['spam_block_until']
    return None, None

def update_spamblock_check(account_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE accounts SET spam_checked_at = NOW() WHERE id = %s",
        (account_id,)
    )
    conn.commit()
    cur.close()
    conn.close()

def update_account_info(account_id, username=None, first_name=None, last_name=None, about=None, banned=None):
    conn = get_db_connection()
    cur = conn.cursor()

    fields = []
    values = []

    if username is not None:
        fields.append("username = %s")
        values.append(username)

    if first_name is not None:
        fields.append("first_name = %s")
        values.append(first_name)

    if last_name is not None:
        fields.append("last_name = %s")
        values.append(last_name)

    if about is not None:
        fields.append("about = %s")
        values.append(about)


    if fields:
        query = f"UPDATE accounts SET {', '.join(fields)} WHERE id = %s"
        values.append(account_id)
        cur.execute(query, tuple(values))
        conn.commit()

    cur.close()
    conn.close()




def get_all_groups():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM account_groups ORDER BY name")
    groups = cur.fetchall()
    cur.close()
    conn.close()
    return groups

def delete_group_by_id(group_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM account_groups WHERE id = %s", (group_id,))
    conn.commit()
    cur.close()
    conn.close()

def move_accounts_to_group(account_ids, group_id):
    conn = get_db_connection()
    cur = conn.cursor()

    # Обновляем группу для всех выбранных аккаунтов
    cur.execute(
        f"UPDATE accounts SET group_id = %s WHERE id = ANY(%s)",
        (group_id, account_ids)
    )

    conn.commit()
    cur.close()
    conn.close()

def clear_old_logs(days_to_keep=7, max_records=5000):
    conn = get_db_connection()
    cur = conn.cursor()

    # Удалить логи старше N дней
    cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
    cur.execute(
        "DELETE FROM logs WHERE timestamp < %s",
        (cutoff_date,)
    )

    # Ограничение по количеству логов
    cur.execute(
        """
        DELETE FROM logs WHERE id NOT IN (
            SELECT id FROM logs ORDER BY timestamp DESC LIMIT %s
        )
        """,
        (max_records,)
    )

    conn.commit()
    cur.close()
    conn.close()
    
def update_log_settings(days_to_keep, max_records):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE log_settings
        SET days_to_keep = %s, max_records = %s
        """,
        (days_to_keep, max_records)
    )

    conn.commit()
    cur.close()
    conn.close()

def get_available_accounts():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, phone, username
        FROM accounts
        WHERE is_banned = FALSE
    """)
    
    accounts = cur.fetchall()
    cur.close()
    conn.close()
    
    return accounts


def get_tasks_by_parent(parent_id):
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM tasks WHERE parent_id = %s ORDER BY id", (parent_id,))
        return cur.fetchall()
        conn.close()

    
def delete_account_by_id(account_id):
    conn = get_connection()
    cur = conn.cursor()

    # Сначала отвязываем аккаунт от всех завершённых задач
    cur.execute("""
        UPDATE tasks
        SET account_id = NULL
        WHERE account_id = %s AND status IN ('done', 'error', 'canceled')
    """, (account_id,))

    # После отвязки — удаляем аккаунт
    cur.execute("""
        DELETE FROM accounts WHERE id = %s
    """, (account_id,))

    conn.commit()
    cur.close()
    conn.close()


def is_account_exists(phone=None, username=None):
    from app.db import get_db_connection

    conn = get_db_connection()
    cur = conn.cursor()

    if phone:
        cur.execute("SELECT id FROM accounts WHERE phone = %s", (phone,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return True

    if username:
        cur.execute("SELECT id FROM accounts WHERE username = %s", (username,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return True

    cur.close()
    conn.close()
    return False
    
def create_account(session_string, proxy_type, proxy_host, proxy_port, proxy_username, proxy_password, phone=None, username=None):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO accounts 
        (session_string, proxy_type, proxy_host, proxy_port, proxy_username, proxy_password, phone, username, status, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'new', NOW())
    """, (
        session_string,
        proxy_type,
        proxy_host,
        proxy_port,
        proxy_username,
        proxy_password,
        phone,
        username
    ))

    conn.commit()
    cur.close()
    conn.close()

def update_account_status_to_active(account_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE accounts SET status = %s WHERE id = %s",
                ('active', account_id)
            )
            conn.commit()
    finally:
        conn.close()

def update_account_status_to_banned(account_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE accounts SET status = %s WHERE id = %s",
                ('banned', account_id)
            )
            conn.commit()
    finally:
        conn.close()

def update_account_status_to_needs_login(account_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE accounts SET status = %s WHERE id = %s",
                ('needs_login', account_id)
            )
            conn.commit()
    finally:
        conn.close()

def update_account_status_to_proxy_error(account_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE accounts SET status = %s WHERE id = %s", ('proxy_error', account_id))
    conn.commit()
    cur.close()
    conn.close()

def update_account_status_to_unknown(account_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE accounts SET status = %s WHERE id = %s", ('unknown', account_id))
    conn.commit()
    cur.close()
    conn.close()

def update_proxy_status(account_id, status):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE accounts SET proxy_status = %s WHERE id = %s", (status, account_id))
    conn.commit()
    cur.close()
    conn.close()

def update_datestatus(account_id, datestatus):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE accounts SET datestatus = %s WHERE id = %s", (datestatus, account_id))
    conn.commit()
    cur.close()
    conn.close()

def update_spamblock_check_full(account_id, is_blocked=False, block_until=None, reason=None):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE accounts
        SET is_spam_blocked = %s,
            spam_block_until = %s,
            spam_block_reason = %s,
            spam_checked_at = NOW()
        WHERE id = %s
    """, (is_blocked, block_until, reason, account_id))
    conn.commit()
    cur.close()
    conn.close()

def save_proxy(host, port, username=None, password=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO proxies (host, port, username, password, status)
        VALUES (%s, %s, %s, %s, 'unknown');
    """, (host, port, username, password))
    conn.commit()
    cur.close()
    conn.close()

def get_all_proxies():
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM proxies;")
    proxies = cur.fetchall()
    cur.close()
    conn.close()
    return proxies

def get_proxy_by_id(proxy_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM proxies WHERE id = %s;", (proxy_id,))
    proxy = cur.fetchone()
    cur.close()
    conn.close()
    return proxy

def update_proxy_status_by_id(proxy_id, status):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE proxies
        SET status = %s
        WHERE id = %s;
    """, (status, proxy_id))
    conn.commit()
    cur.close()
    conn.close()

def delete_proxy_by_id(proxy_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM proxies WHERE id = %s;", (proxy_id,))
    conn.commit()
    cur.close()
    conn.close()

def delete_bad_proxies():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM proxies WHERE status = 'bad';")
    conn.commit()
    cur.close()
    conn.close()

def count_accounts_using_proxy(host, port, username=None, password=None):
    conn = get_connection()
    cur = conn.cursor()
    
    query = """
        SELECT COUNT(*) FROM accounts
        WHERE proxy_host = %s
          AND proxy_port = %s
          AND (proxy_username = %s OR (proxy_username IS NULL AND %s IS NULL))
          AND (proxy_password = %s OR (proxy_password IS NULL AND %s IS NULL))
    """
    cur.execute(query, (host, port, username, username, password, password))
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count

def proxy_exists(host, port, username=None, password=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM proxies
        WHERE host = %s
          AND port = %s
          AND (username = %s OR (username IS NULL AND %s IS NULL))
          AND (password = %s OR (password IS NULL AND %s IS NULL))
    """, (host, port, username, username, password, password))
    exists = cur.fetchone()[0] > 0
    cur.close()
    conn.close()
    return exists

def account_has_active_tasks(account_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM tasks
        WHERE account_id = %s
          AND status IN ('pending', 'in_progress')
    """, (account_id,))
    active_tasks = cur.fetchone()[0] > 0
    cur.close()
    conn.close()
    return active_tasks

def update_account_proxy(account_id, host, port, username=None, password=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE accounts SET proxy_host = %s, proxy_port = %s, proxy_username = %s, proxy_password = %s WHERE id = %s",
        (host, port, username, password, account_id)
    )
    conn.commit()
    cur.close()
    conn.close()

def get_task_logs_by_task_id(task_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT timestamp, message FROM task_logs WHERE task_id = %s ORDER BY timestamp", (task_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_account_by_phone(phone: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM accounts WHERE phone = %s
    """, (phone,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def insert_task_del_log(task_id: int, account_id: int, log_text: str):
    from app.db import get_db_connection  # если используешь отдельную функцию для подключения
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        INSERT INTO task_del (task_id, account_id, log_text)
        VALUES (%s, %s, %s)
    """
    cursor.execute(query, (task_id, account_id, log_text))
    conn.commit()
    cursor.close()
    conn.close()

def create_task_entry(task_type, created_by, payload=None):
    import json
    conn = get_connection()
    cur = conn.cursor()
    # Только если payload не None и не строка — сериализуй
    if payload is not None and not isinstance(payload, str):
        payload = json.dumps(payload)
    cur.execute("""
        INSERT INTO tasks (type, created_by, payload)
        VALUES (%s, %s, %s) RETURNING id
    """, (task_type, created_by, payload))
    task_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return task_id



def get_task_del_logs(task_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT log_text FROM task_del WHERE task_id = %s ORDER BY account_id", (task_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [row[0] for row in rows]


def get_task_del_logs_by_task_id(task_id: int):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT account_id, log_text
        FROM task_del
        WHERE task_id = %s
        ORDER BY account_id
    """, (task_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def insert_task_create_log(task_id: int, account_id: int, log_text: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO task_create (task_id, account_id, log_text) VALUES (%s, %s, %s)",
        (task_id, account_id, log_text)
    )
    conn.commit()
    cursor.close()
    conn.close()


def update_task_accounts_count(task_id: int, count: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE tasks SET accounts_count = %s WHERE id = %s",
        (count, task_id)
    )
    conn.commit()
    cursor.close()
    conn.close()

def delete_task_create_logs_by_task_id(task_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM task_create WHERE task_id = %s;", (task_id,))
    conn.commit()
    cur.close()
    conn.close()
    
def log_check_group(task_id, account, group_link, result, members=None, error=None):
    if task_id is None:
        return  # Просто не пишем лог если нет task_id
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO check_groups_log
            (task_id, account_id, account_username, checked_group, result, members, error_message)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            task_id,
            account.get("id"),
            account.get("username") or account.get("phone"),
            group_link,
            result,   # "ok", "small", "bad", "error"
            members,
            error
        )
    )
    conn.commit()
    cur.close()
    conn.close()


def log_spambot_message(account_id, from_who, message):
    from_who = from_who[:16]
    now = datetime.now()
    with psycopg2.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO spambot_logs (account_id, timestamp, from_who, message) VALUES (%s, %s, %s, %s)",
                (account_id, now, from_who, message)
            )
        conn.commit()

def has_spambot_log(account_id):
    with psycopg2.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM spambot_logs WHERE account_id = %s", (account_id,)
            )
            count = cur.fetchone()[0]
            return count > 0

def get_spambot_log(account_id):
    with psycopg2.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT timestamp, from_who, message FROM spambot_logs WHERE account_id = %s ORDER BY timestamp",
                (account_id,)
            )
            return [
                {"timestamp": row[0], "from_who": row[1], "message": row[2]}
                for row in cur.fetchall()
            ]
            
#Функция для получения лога из базы
def get_spambot_logs_for_account(account_id):
    with psycopg2.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT timestamp, from_who, message FROM spambot_logs WHERE account_id=%s ORDER BY timestamp",
                (account_id,)
            )
            rows = cur.fetchall()
            return [
                {"timestamp": row[0], "from_who": row[1], "message": row[2]}
                for row in rows
            ]
            
def create_account_group(name, emoji):
    with psycopg2.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO account_groups (name, emoji) VALUES (%s, %s) RETURNING id",
                (name, emoji)
            )
            return cur.fetchone()[0]

def get_account_groups():
    with psycopg2.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, emoji FROM account_groups ORDER BY id")
            return [{"id": row[0], "name": row[1], "emoji": row[2]} for row in cur.fetchall()]

def get_account_groups_with_count():
    with psycopg2.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT g.id, g.name, g.emoji, COUNT(a.id) as count
                FROM account_groups g
                LEFT JOIN accounts a ON a.group_id = g.id
                GROUP BY g.id
                ORDER BY g.id
            """)
            return [{"id": row[0], "name": row[1], "emoji": row[2], "count": row[3]} for row in cur.fetchall()]

def update_account_status_to_frozen(account_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE accounts SET status = %s WHERE id = %s", ('freeze', account_id))
        conn.commit()
    finally:
        conn.close()

def save_group_result(task_id, user_id, account_id, keyword, group):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO search_groups_results 
        (task_id, user_id, account_id, keyword, group_id, title, username, members)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (task_id, user_id, account_id, keyword, group['id'], group['title'], group['username'], group['members'])
    )
    conn.commit()
    cur.close()
    conn.close()

def get_group_results_by_task(task_id, user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT keyword, title, username, members 
        FROM search_groups_results
        WHERE task_id=%s AND user_id=%s
        ORDER BY keyword, members DESC NULLS LAST
    """, (task_id, user_id))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_active_accounts():
    from app.db import get_db_connection  # если используешь отдельную функцию подключения
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, username, phone, session_string
        FROM accounts
        WHERE status = 'active'
        ORDER BY RANDOM()
    """)
    rows = cur.fetchall()
    columns = [desc[0] for desc in cur.description]
    accounts = [dict(zip(columns, row)) for row in rows]
    cur.close()
    conn.close()
    return accounts

def update_account_status(account_id, status):
    from app.db import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE accounts SET status = %s WHERE id = %s
    """, (status, account_id))
    conn.commit()
    cur.close()
    conn.close()

def get_mass_search_tasks(limit=10):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT * FROM tasks WHERE type='mass_group_search' ORDER BY created_at DESC LIMIT %s", (limit,)
    )
    tasks = cur.fetchall()
    cur.close()
    conn.close()
    return tasks

def save_task_result(task_id, result_text):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO task_results (task_id, result) VALUES (%s, %s) ON CONFLICT (task_id) DO UPDATE SET result = EXCLUDED.result",
        (task_id, result_text)
    )
    conn.commit()
    cur.close()
    conn.close()

def get_task_result_text(task_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT result FROM task_results WHERE task_id = %s", (task_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None

def update_task_progress(task_id, processed_keywords, total_keywords, groups_found):

    conn = get_connection()
    cur = conn.cursor()
    progress = json.dumps({
        "processed_keywords": processed_keywords,
        "total_keywords": total_keywords,
        "groups_found": groups_found
    })
    cur.execute("UPDATE tasks SET progress=%s WHERE id=%s", (progress, task_id))
    conn.commit()
    cur.close()
    conn.close()

def insert_join_groups_log(task_id, account_id, group_link, status, message=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO join_groups_log (task_id, account_id, group_link, status, message) VALUES (%s, %s, %s, %s, %s)",
        (task_id, account_id, group_link, status, message)
    )
    conn.commit()
    cur.close()
    conn.close()

def get_join_groups_logs(task_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM join_groups_log WHERE task_id = %s ORDER BY account_id, id", (task_id,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_task_summary(task_id):
    # тут получи реальные данные из БД, сейчас просто пример
    summary = [
        (1, {"no_captcha": ["группа1", "группа2"], "with_captcha": ["группа3"]}),
        (2, {"no_captcha": ["группа4"], "with_captcha": []}),
    ]
    total_groups = 5  # Всего групп в задаче
    return summary, total_groups


def get_all_join_groups_tasks():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, type, created_at
        FROM tasks
        WHERE type = 'join_groups'
        ORDER BY id DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    tasks = []
    for row in rows:
        tasks.append({
            "id": row[0],
            "type": row[1],
            "created_at": row[2]
        })
    return tasks

def get_join_group_task_by_id(task_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""SELECT * FROM tasks WHERE id = %s AND type = 'join_groups'""", (task_id,))
    task = cur.fetchone()
    cur.close()
    conn.close()
    if not task:
        return None
    payload = task.get("payload")
    if payload and isinstance(payload, str):
        import json
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    else:
        payload = payload or {}
    task.update(payload)
    return task


def update_task_payload(task_id, payload: dict):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE tasks SET payload = %s WHERE id = %s
    """, (json.dumps(payload), task_id))
    conn.commit()
    cur.close()
    conn.close()
    
def get_task_progress_and_status(task_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT progress, status FROM tasks WHERE id=%s", (task_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row or not row[0]:
        return {}, "pending"
    import json
    return json.loads(row[0]), row[1]

def update_task_progress_status(task_id, progress: dict, status: str = None):
    conn = get_connection()
    cur = conn.cursor()
    if status is not None:
        cur.execute("UPDATE tasks SET progress = %s, status = %s WHERE id = %s", (json.dumps(progress), status, task_id))
    else:
        cur.execute("UPDATE tasks SET progress = %s WHERE id = %s", (json.dumps(progress), task_id))
    conn.commit()
    cur.close()
    conn.close()


# --- LIKE COMMENTS: DB HELPERS ---

def create_like_comments_task(created_by: int, payload: dict = None) -> int:
    import json, datetime
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO tasks (type, status, created_by, scheduled_at, payload) VALUES (%s,%s,%s,%s,%s) RETURNING id",
        ("like_comments", "active", created_by, datetime.datetime.utcnow(), json.dumps(payload or {}))
    )
    task_id = cur.fetchone()[0]
    conn.commit()
    cur.close(); conn.close()
    return task_id

def insert_like_log(task_id: int, account_id: int, channel: str, post_id: int, comment_id: int, reaction: str, status: str, message: str = None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO like_comments_log (task_id, account_id, channel, post_id, comment_id, reaction, status, message) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (task_id, account_id, channel, post_id, comment_id, reaction, status, message)
    )
    conn.commit()
    cur.close(); conn.close()

def reacted_already(account_id: int, comment_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM like_comments_log WHERE account_id=%s AND comment_id=%s AND status='ok' LIMIT 1",
        (account_id, comment_id)
    )
    row = cur.fetchone()
    cur.close(); conn.close()
    return bool(row)

def upsert_watch_state(task_id: int, account_id: int, channel: str, last_seen_post_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO like_watch_state (task_id, account_id, channel, last_seen_post_id)
        VALUES (%s,%s,%s,%s)
        ON CONFLICT (task_id, account_id, channel)
        DO UPDATE SET last_seen_post_id = EXCLUDED.last_seen_post_id, updated_at = NOW()
    """, (task_id, account_id, channel, last_seen_post_id))
    conn.commit()
    cur.close(); conn.close()

def get_watch_state(task_id: int, account_id: int, channel: str) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT last_seen_post_id FROM like_watch_state WHERE task_id=%s AND account_id=%s AND channel=%s",
                (task_id, account_id, channel))
    row = cur.fetchone()
    cur.close(); conn.close()
    return int(row[0]) if row and row[0] else 0


def get_like_watch_state(task_id:int, account_id:int, channel:str):
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT last_post_id FROM like_watch_state
                   WHERE task_id=%s AND account_id=%s AND channel_username=%s""",
                (task_id, account_id, channel))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row[0] if row else None

def upsert_like_watch_state(task_id:int, account_id:int, channel:str, last_post_id:int|None):
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO like_watch_state (task_id, account_id, channel_username, last_post_id)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (task_id, account_id, channel_username)
        DO UPDATE SET last_post_id = EXCLUDED.last_post_id, last_checked_at = now()
    """, (task_id, account_id, channel, last_post_id))
    conn.commit(); cur.close(); conn.close()

def reacted_already(task_id:int, account_id:int, channel:str, post_id:int, comment_id:int) -> bool:
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT 1 FROM like_reactions
                   WHERE task_id=%s AND account_id=%s AND channel_username=%s AND post_id=%s AND comment_id=%s""",
                (task_id, account_id, channel, post_id, comment_id))
    ok = cur.fetchone() is not None
    cur.close(); conn.close()
    return ok

def insert_like_reaction(task_id:int, account_id:int, channel:str, post_id:int, comment_id:int):
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""INSERT INTO like_reactions (task_id, account_id, channel_username, post_id, comment_id)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (task_id, account_id, channel, post_id, comment_id))
    conn.commit(); cur.close(); conn.close()

# (опционально, для «докидывания» каналов в задачу прямо в payload JSONB)
def append_channels_to_like_task(task_id:int, new_channels:list[str]):
    """Атомично обновляет tasks.payload->'channels' (PostgreSQL JSONB) и убирает дубли."""
    conn = get_connection(); cur = conn.cursor()

    norm = [c.replace('https://t.me/','').replace('http://t.me/','').replace('@','').strip()
            for c in new_channels if c and c.strip()]
    if not norm:
        return

    # Достаём текущий payload
    cur.execute("SELECT payload FROM tasks WHERE id=%s", (task_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close(); return

    import json
    payload = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    old = payload.get("channels", [])
    merged = list(dict.fromkeys(old + norm))  # уникализация с сохранением порядка
    payload["channels"] = merged

    cur.execute("UPDATE tasks SET payload=%s WHERE id=%s", (json.dumps(payload, ensure_ascii=False), task_id))
    conn.commit(); cur.close(); conn.close()


LOCK_SCOPE_LIKE = 1001  # любое число; можешь сделать по типам задач: like=1001, join=1002 и т.д.

def try_lock_account(account_id: int, scope: int = LOCK_SCOPE_LIKE) -> bool:
    with get_conn().cursor() as cur:  # используй ваш способ получить conn
        cur.execute("SELECT pg_try_advisory_lock(%s::bigint, %s::bigint);", (scope, account_id))
        return bool(cur.fetchone()[0])

def unlock_account(account_id: int, scope: int = LOCK_SCOPE_LIKE) -> bool:
    with get_conn().cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s::bigint, %s::bigint);", (scope, account_id))
        return bool(cur.fetchone()[0])

# app/db.py

def get_ok_channels_for_task(task_id: int) -> list[str]:
    """
    Возвращает уникальные каналы, где были УСПЕШНЫЕ лайки для задачи.
    1) Пытаемся из like_reactions (channel_username)
    2) Если пусто — из like_comments_log по status='ok' (channel)
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # 1) like_reactions
            try:
                cur.execute(
                    "SELECT DISTINCT channel_username FROM like_reactions WHERE task_id=%s ORDER BY 1 ASC",
                    (task_id,)
                )
                rows = cur.fetchall()
                chans = []
                for r in rows:
                    if isinstance(r, (list, tuple)):
                        chans.append((r[0] or "").strip())
                    else:
                        chans.append((r.get("channel_username") or "").strip())
                chans = [c for c in chans if c]
                if chans:
                    return chans
            except Exception:
                pass  # таблицы может не быть — ок

            # 2) like_comments_log (status='ok')
            try:
                cur.execute(
                    "SELECT DISTINCT channel FROM like_comments_log WHERE task_id=%s AND status='ok' ORDER BY 1 ASC",
                    (task_id,)
                )
                rows = cur.fetchall()
                chans = []
                for r in rows:
                    if isinstance(r, (list, tuple)):
                        chans.append((r[0] or "").strip())
                    else:
                        chans.append((r.get("channel") or "").strip())
                chans = [c for c in chans if c]
                if chans:
                    return chans
            except Exception:
                pass

    finally:
        try:
            conn.close()
        except Exception:
            pass

    return []


# --- 2FA TASKS DAO ---



def create_twofa_task(user_id: int,
                      mode: str,
                      kill_other: bool,
                      accounts: list[dict],
                      new_password: str | None,
                      old_password: str | None) -> int:
    """
    Создаёт запись задачи и возвращает id.
    accounts: [{account_id, username}]
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO twofa_tasks (user_id, mode, kill_other, new_password, old_password, accounts_json, status)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'pending')
        RETURNING id
    """, (user_id, mode, kill_other, new_password, old_password, json.dumps(accounts)))
    task_id = cur.fetchone()[0]
    conn.commit()
    cur.close(); conn.close()
    return task_id


def set_twofa_task_status(task_id: int, status: str, started: bool = False, finished: bool = False) -> None:
    """
    Обновляет статус; по флагам проставляет started_at/finished_at.
    """
    sets = ["status = %s"]
    args = [status]
    if started:
        sets.append("started_at = NOW()")
    if finished:
        sets.append("finished_at = NOW()")
    sql = f"UPDATE twofa_tasks SET {', '.join(sets)} WHERE id = %s"
    args.append(task_id)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(sql, tuple(args))
    conn.commit()
    cur.close(); conn.close()


def add_twofa_log(task_id: int, account_id: int | None, username: str | None,
                  ok: bool, removed_other: bool, message: str) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO twofa_logs (task_id, account_id, username, ok, removed_other, message)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (task_id, account_id, username, ok, removed_other, message or ""))
    conn.commit()
    cur.close(); conn.close()


def read_twofa_task(task_id: int) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user_id, mode, kill_other, new_password, old_password,
               accounts_json, status, created_at, started_at, finished_at
        FROM twofa_tasks WHERE id = %s
    """, (task_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return None
    (id_, user_id, mode, kill_other, new_pw, old_pw,
     accounts_json, status, created_at, started_at, finished_at) = row
    return {
        "id": id_,
        "user_id": user_id,
        "mode": mode,
        "kill_other": kill_other,
        "new_password": new_pw,
        "old_password": old_pw,
        "accounts_json": accounts_json or [],
        "status": status,
        "created_at": created_at,
        "started_at": started_at,
        "finished_at": finished_at,
    }


def read_twofa_logs(task_id: int, limit: int = 1000) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT ts, account_id, username, ok, removed_other, message
        FROM twofa_logs
        WHERE task_id = %s
        ORDER BY ts
        LIMIT %s
    """, (task_id, limit))
    rows = cur.fetchall()
    cur.close(); conn.close()
    out = []
    for ts, acc_id, username, ok, rem, msg in rows:
        out.append({
            "ts": ts, "account_id": acc_id, "username": username,
            "ok": ok, "removed_other": rem, "message": msg
        })
    return out


# --- СПИСОК 2FA-задач для меню (как get_tasks_by_type) ---

def get_twofa_tasks(limit: int = 20) -> list[dict]:
    """
    Возвращает задачи 2FA в формате, похожем на get_tasks_by_type(...),
    чтобы отрисовать список в tasks_view.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT id, status, created_at, started_at, finished_at, mode, kill_other, accounts_json
        FROM twofa_tasks
        ORDER BY id DESC
        LIMIT %s
    """, (limit,))
    rows = cur.fetchall()
    cur.close(); conn.close()

    tasks = []
    for id_, status, created_at, started_at, finished_at, mode, kill_other, accounts_json in rows:
        tasks.append({
            "id": id_,
            "type": "twofa",
            "status": status,
            # под твой tasks_view: многие экраны ожидают scheduled_at
            "scheduled_at": created_at,
            "created_at": created_at,
            "started_at": started_at,
            "finished_at": finished_at,
            "payload": {
                "mode": mode,
                "kill_other": kill_other,
                "accounts": accounts_json or [],
                "accounts_count": len(accounts_json or []),
            }
        })
    return tasks

def count_twofa_logs(task_id: int) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM twofa_logs WHERE task_id = %s", (task_id,))
    n = cur.fetchone()[0] if cur.rowcount is not None else 0
    cur.close(); conn.close()
    return int(n or 0)

def delete_twofa_task(task_id: int) -> int:
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("DELETE FROM public.twofa_tasks WHERE id=%s", (task_id,))
        n = cur.rowcount or 0
        conn.commit()
        return n
    finally:
        cur.close(); conn.close()


@contextmanager
def _tx(conn):
    try:
        yield
        conn.commit()
    except:
        conn.rollback()
        raise

def swap_account_string_session(conn, account_id: int, new_ss: str):
    with _tx(conn), conn.cursor() as cur:
        # сохранить историю
        cur.execute("""
            INSERT INTO account_session_history (account_id, old_session)
            SELECT id, string_session FROM accounts WHERE id = %s
        """, (account_id,))
        # обновить основную сессию
        cur.execute("""
            UPDATE accounts SET string_session = %s, reauthorized_at = now()
            WHERE id = %s
        """, (new_ss, account_id))




def ensure_api_keys_table() -> None:
    """
    Создаёт таблицу api_keys, если её нет.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
              api_id    INTEGER PRIMARY KEY,
              api_hash  TEXT    NOT NULL,
              label     TEXT
            );
        """)
        conn.commit()

def get_all_api_keys() -> List[Dict[str, Any]]:
    """
    Возвращает список ключей вида:
    [{'api_id': 12345, 'api_hash': 'xxxx', 'label': '...'}, ...]
    """
    ensure_api_keys_table()
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT api_id, api_hash, label FROM api_keys ORDER BY api_id;")
        rows = cur.fetchall()
        # Приведём к обычным dict (на случай если где-то не нравится RealDictRow)
        return [dict(r) for r in rows]



def get_all_api_keys_for_checker() -> List[Dict[str, Any]]:
    """
    Возвращает [{'api_id': int, 'api_hash': str, 'name': Optional[str]}] из public.api_keys
    НИЧЕГО не меняет в БД.
    """
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT api_id, api_hash, name FROM public.api_keys ORDER BY id;")
        rows = cur.fetchall()
        return [dict(r) for r in rows]



def create_comment_check_task(created_by: int, channels: list[str], accounts: list[dict], concurrency: int | None = None) -> int:
    """
    Создаёт задачу типа 'check_comments'.
    payload: { "channels":[...], "accounts":[...], "status":"pending", "total_channels":N, "checked":0, "concurrency":M }
    """
    import json
    if concurrency is None:
        concurrency = max(1, min(len(accounts) or 1, 3))

    conn = get_connection(); cur = conn.cursor()
    payload = json.dumps({
        "channels": channels,
        "accounts": accounts,
        "status": "pending",
        "total_channels": len(channels),
        "checked": 0,
        "concurrency": int(concurrency),
    }, ensure_ascii=False)

    cur.execute("""
        INSERT INTO tasks (type, status, created_by, payload, scheduled_at, is_active)
        VALUES ('check_comments', 'pending', %s, %s, NOW(), TRUE)
        RETURNING id
    """, (created_by, payload))
    task_id = cur.fetchone()[0]
    conn.commit(); cur.close(); conn.close()
    return task_id


def insert_comment_check_log(task_id: int, account_id: int | None, channel: str,
                             can_comment: bool | None, mode: str | None, message: str | None):
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO comment_check_log (task_id, account_id, channel, can_comment, mode, message)
        VALUES (%s,%s,%s,%s,%s,%s)
    """, (task_id, account_id, channel, can_comment, mode, message))
    conn.commit(); cur.close(); conn.close()

def get_comment_check_logs(task_id: int):
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT account_id, channel, can_comment, mode, message, checked_at
        FROM comment_check_log
        WHERE task_id=%s
        ORDER BY channel, checked_at
    """, (task_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows

def update_comment_check_progress(task_id: int, checked: int, total: int, status: str | None = None):
    import json as _json
    conn = get_connection(); cur = conn.cursor()

    # 1) достаём текущий payload
    cur.execute("SELECT payload FROM tasks WHERE id=%s", (task_id,))
    row = cur.fetchone()
    payload = {}
    if row and row[0]:
        if isinstance(row[0], dict):
            payload = row[0]
        else:
            try:
                payload = _json.loads(row[0])
            except Exception:
                payload = {}

    # 2) обновляем поля прогресса
    payload["checked"] = int(checked)
    payload["total_channels"] = int(total)
    if status:
        payload["status"] = status

    payload_json = _json.dumps(payload, ensure_ascii=False)

    # 3) делаем корректный UPDATE (две явные ветки, чтобы не путать плейсхолдеры)
    if status:
        cur.execute(
            "UPDATE tasks SET payload=%s, status=%s, updated_at=NOW() WHERE id=%s",
            (payload_json, status, task_id),
        )
    else:
        cur.execute(
            "UPDATE tasks SET payload=%s, updated_at=NOW() WHERE id=%s",
            (payload_json, task_id),
        )

    conn.commit()
    cur.close(); conn.close()

def log_task_event_safe(task_id: int, message: str, status: str = "info", account_id=None):
    """
    Безопасная версия логирования события задачи.
    account_id — опционален (может быть None).
    """
    # Скопируйте сюда тело оригинальной log_task_event,
    # но убедитесь, что account_id обрабатывается корректно
    # (например, сохраняется в БД только если не None).

    # Пример (адаптируйте под вашу БД):
    from datetime import datetime
    # cursor.execute(
    #     "INSERT INTO task_logs (task_id, message, status, account_id, created_at) VALUES (?, ?, ?, ?, ?)",
    #     (task_id, message, status, account_id, datetime.utcnow())
    # )
    # connection.commit()

    # Если у вас уже есть реализация в log_task_event — просто вызовите её с account_id=None по умолчанию:
    # Но лучше скопировать логику, чтобы не зависеть от сигнатуры старой функции.
    
def ensure_accounts_metadata_columns():
    """
    Проверяет наличие колонок метаданных в таблице accounts.
    При отсутствии — добавляет их. Безопасна для повторного вызова.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'accounts';
            """)
            existing_columns = {row[0] for row in cur.fetchall()}

            required_columns = {
                "device_model": "TEXT",
                "system_version": "TEXT",
                "app_version": "TEXT",
                "lang_code": "TEXT",
                "system_lang_code": "TEXT",
                "is_premium": "BOOLEAN DEFAULT FALSE",
                "register_time": "BIGINT"  # Unix timestamp
            }

            added = []
            for col_name, col_type in required_columns.items():
                if col_name not in existing_columns:
                    cur.execute(f'ALTER TABLE public.accounts ADD COLUMN "{col_name}" {col_type};')
                    added.append(col_name)

            if added:
                print(f"[DB] Добавлены колонки в accounts: {', '.join(added)}", flush=True)
            else:
                print("[DB] Все колонки метаданных уже существуют", flush=True)

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Ошибка при обновлении структуры accounts: {e}", flush=True)
        raise
    finally:
        conn.close()

        
def create_account_with_metadata(
    session_string: str,
    proxy_type: str,
    proxy_host: str,
    proxy_port: int,
    proxy_username: str | None,
    proxy_password: str | None,
    phone: str | None = None,
    username: str | None = None,
    # Метаданные из JSON
    device_model: str | None = None,
    system_version: str | None = None,
    app_version: str | None = None,
    lang_code: str | None = None,
    system_lang_code: str | None = None,
    is_premium: bool = False,
    register_time: int | None = None,  # unix ts или None
):
    """
    Создаёт аккаунт с поддержкой метаданных из JSON. Возвращает id созданной записи.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO accounts 
                (session_string, proxy_type, proxy_host, proxy_port, proxy_username, proxy_password,
                 phone, username, status, created_at,
                 device_model, system_version, app_version,
                 lang_code, system_lang_code, is_premium, register_time)
            VALUES 
                (%s, %s, %s, %s, %s, %s,
                 %s, %s, 'new', NOW(),
                 %s, %s, %s,
                 %s, %s, %s, %s)
            RETURNING id
        """, (
            session_string,
            proxy_type,
            proxy_host,
            proxy_port,
            proxy_username,
            proxy_password,
            phone,
            username,
            device_model,
            system_version,
            app_version,
            lang_code,
            system_lang_code,
            is_premium,
            register_time
        ))
        new_id = cur.fetchone()[0]
        conn.commit()
        return new_id
    except Exception as e:
        conn.rollback()
        print(f"[DB] create_account_with_metadata error: {e}", flush=True)
        raise
    finally:
        cur.close()
        conn.close()

def merge_account_metadata_by_session(session_string: str, meta: dict) -> int:
    """
    Заполняет ТОЛЬКО пустые (NULL/пустая строка) поля метаданных у аккаунта с данным session_string.
    Возвращает количество затронутых строк (0/1).
    """
    if not meta:
        return 0

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE public.accounts
                   SET device_model      = COALESCE(NULLIF(device_model, ''), %s),
                       system_version    = COALESCE(NULLIF(system_version, ''), %s),
                       app_version       = COALESCE(NULLIF(app_version, ''), %s),
                       lang_code         = COALESCE(NULLIF(lang_code, ''), %s),
                       system_lang_code  = COALESCE(NULLIF(system_lang_code, ''), %s),
                       -- булевы/числовые трогаем только если NULL
                       is_premium        = COALESCE(is_premium, %s),
                       register_time     = COALESCE(register_time, %s)
                 WHERE session_string = %s
            """, (
                meta.get("device_model"),
                meta.get("system_version"),
                meta.get("app_version"),
                meta.get("lang_code"),
                meta.get("system_lang_code"),
                (bool(meta["is_premium"]) if "is_premium" in meta and meta["is_premium"] is not None else None),
                meta.get("register_time"),
                session_string,
            ))
            affected = cur.rowcount
        conn.commit()
        return affected
    except Exception as e:
        conn.rollback()
        print(f"[DB] merge_account_metadata_by_session error: {e}", flush=True)
        raise
    finally:
        conn.close()



def account_exists_by_session(session_string: str) -> bool:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM accounts WHERE session_string = %s LIMIT 1", (session_string,))
            return cur.fetchone() is not None
    finally:
        conn.close()

def get_account_by_session_string(session_string: str) -> dict | None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT *
                FROM public.accounts
                WHERE session_string = %s
                LIMIT 1
            """, (session_string,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
    finally:
        conn.close()



def get_task_payload_dict(task_id: int) -> dict:
    conn = get_connection(); cur = conn.cursor()
    cur.execute("SELECT payload FROM tasks WHERE id=%s", (task_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row: return {}
    payload = row[0]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    return payload or {}

def save_task_payload_dict(task_id: int, payload: dict):
    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE tasks SET payload=%s, updated_at=NOW()",
                (json.dumps(payload, ensure_ascii=False),))
    conn.commit(); cur.close(); conn.close()

def remove_account_from_like_task(task_id: int, account_id: int, reason: str | None = None):
    """Убирает аккаунт из assignments и складывает его оставшиеся каналы обратно в общий пул (channels_pool)."""
    payload = get_task_payload_dict(task_id)
    assignments = payload.get("assignments", {})  # {account_id(str): [channels]}
    pool = payload.get("channels_pool", [])       # общий пул, если используешь
    acc_key = str(account_id)

    remaining = assignments.pop(acc_key, [])
    # вернём оставшиеся в пул (без дублей, сохраняя порядок)
    if remaining:
        merged = list(dict.fromkeys(remaining + pool))
        payload["channels_pool"] = merged

    # пометим причину
    bad = payload.get("failed_accounts", {})
    bad[acc_key] = {"ts": datetime.utcnow().isoformat(), "reason": reason or "fatal"}
    payload["failed_accounts"] = bad

    save_task_payload_dict(task_id, payload)

def redistribute_channels_round_robin(task_id: int):
    """Забирает из channels_pool и равномерно раскладывает по живым аккаунтам из assignments."""
    payload = get_task_payload_dict(task_id)
    assignments = payload.get("assignments", {})
    pool = payload.get("channels_pool", [])
    if not pool or not assignments:
        return

    acc_ids = [k for k in assignments.keys()]  # строки!
    i = 0
    while pool:
        ch = pool.pop(0)
        # на всякий не пихаем дубли в целевых
        for _ in range(len(acc_ids)):
            target = acc_ids[i % len(acc_ids)]
            i += 1
            lst = assignments.setdefault(target, [])
            if ch not in lst:
                lst.append(ch)
                break

    payload["assignments"] = assignments
    payload["channels_pool"] = pool
    save_task_payload_dict(task_id, payload)


def insert_liked_post(task_id: int, channel: str, post_id: int):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO like_liked_posts (task_id, channel, post_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (task_id, channel, post_id) DO NOTHING
        """, (task_id, channel, post_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def liked_post_already(task_id: int, channel: str, post_id: int) -> bool:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM like_liked_posts WHERE task_id = %s AND channel = %s AND post_id = %s LIMIT 1",
            (task_id, channel, post_id)
        )
        row = cur.fetchone()
        return bool(row)
    finally:
        cur.close()
        conn.close()

def bootstrap_like_tables_once():
    """
    Создаёт таблицы для like-задач, если они не существуют.
    Подключается через PG_BOOTSTRAP_DSN (postgres), выдаёт права PG_APP_OWNER.
    Безопасна для повторного вызова — ничего не перезаписывает.
    """
    bootstrap_dsn = os.getenv("PG_BOOTSTRAP_DSN")
    app_owner = os.getenv("PG_APP_OWNER", "tguser")

    if not bootstrap_dsn:
        print("[BOOTSTRAP] ⚠️ PG_BOOTSTRAP_DSN not set — skipping like tables bootstrap")
        return

    print("[BOOTSTRAP] 🔧 Ensuring like tables exist...")
    try:
        # Подключаемся как суперпользователь
        conn = psycopg2.connect(bootstrap_dsn)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        # 1. like_liked_posts
        cur.execute("""
            CREATE TABLE IF NOT EXISTS like_liked_posts (
                task_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                post_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (task_id, channel, post_id)
            );
        """)

        # 2. like_reactions
        cur.execute("""
            CREATE TABLE IF NOT EXISTS like_reactions (
                task_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                channel_username TEXT NOT NULL,
                post_id INTEGER NOT NULL,
                comment_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (task_id, account_id, channel_username, post_id, comment_id)
            );
        """)

        # 3. like_watch_state
        cur.execute("""
            CREATE TABLE IF NOT EXISTS like_watch_state (
                task_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                last_seen_post_id INTEGER NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (task_id, account_id, channel)
            );
        """)

        # 4. Выдаём права
        for table in ("like_liked_posts", "like_reactions", "like_watch_state"):
            cur.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO {app_owner};")

        cur.close()
        conn.close()
        print("[BOOTSTRAP] ✅ Like tables are ready")

    except Exception as e:
        print(f"[BOOTSTRAP] ❌ Failed to bootstrap like tables: {e}")
        raise
        
from psycopg2.extras import execute_values

from psycopg2 import sql
from psycopg2.extras import execute_values

def bootstrap_blacklist_posts_table(grantee: str = "tguser"):
    """
    Идемпотентный бутстрап: создаёт таблицу/индекс чёрного списка постов
    и выдаёт нужные права пользователю grantee (по умолчанию 'tguser').
    """
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            # 1) таблица + индекс
            cur.execute("""
                CREATE TABLE IF NOT EXISTS like_blacklisted_posts (
                    channel     TEXT    NOT NULL,
                    post_id     BIGINT  NOT NULL,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (channel, post_id)
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_like_blacklisted_posts_channel
                ON like_blacklisted_posts(channel);
            """)

            # 2) права на схему (на случай строгих политик)
            cur.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {};")
                   .format(sql.Identifier("public"), sql.Identifier(grantee))
            )

            # 3) права на таблицу (повторный GRANT — ок)
            cur.execute(
                sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {} TO {};")
                   .format(sql.Identifier("like_blacklisted_posts"),
                           sql.Identifier(grantee))
            )

            # 4) (опционально) права на последовательности схемы public
            cur.execute(
                sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {};")
                   .format(sql.Identifier("public"), sql.Identifier(grantee))
            )
    finally:
        conn.close()


def is_post_blacklisted(channel: str, post_id: int) -> bool:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM like_blacklisted_posts WHERE channel=%s AND post_id=%s LIMIT 1",
                (channel, int(post_id)),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def blacklist_posts_bulk(channel: str, post_ids: list[int]) -> int:
    """Идемпотентная массовая вставка постов в ЧС. Возвращает сколько ПЫТАЛИСЬ вставить (rowcount может быть None)."""
    if not post_ids:
        return 0
    rows = [(channel, int(pid)) for pid in post_ids]
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            q = """
                INSERT INTO like_blacklisted_posts (channel, post_id)
                VALUES %s
                ON CONFLICT (channel, post_id) DO NOTHING
            """
            execute_values(cur, q, rows, template="(%s, %s)")
            # rowcount у execute_values указывает на количество ЗАПРОШЕННЫХ вставок, не фактически добавленных.
            # Для идемпотентности это ок — нам важна сама фиксация в ЧС.
            return cur.rowcount or 0
    finally:
        conn.close()



def blacklist_post(channel: str, post_id: int):
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO like_blacklisted_posts (channel, post_id)
        VALUES (%s, %s)
        ON CONFLICT (channel, post_id) DO NOTHING
    """, (channel, post_id))
    conn.commit(); cur.close(); conn.close()

def get_blacklist_highwater_for_channel(channel: str) -> int:
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(MAX(post_id), 0)
        FROM like_blacklisted_posts
        WHERE channel = %s
    """, (channel,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return int(row[0] or 0)
