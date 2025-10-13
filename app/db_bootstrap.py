# app/db_bootstrap.py
import os
import psycopg2

META_COLUMNS = (
    "device_model",
    "system_version",
    "app_version",
    "lang_code",
    "system_lang_code",
    "is_premium",
    "register_time",
)

BOOTSTRAP_COLUMNS_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='accounts' AND column_name='device_model') THEN
        ALTER TABLE public.accounts ADD COLUMN device_model TEXT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='accounts' AND column_name='system_version') THEN
        ALTER TABLE public.accounts ADD COLUMN system_version TEXT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='accounts' AND column_name='app_version') THEN
        ALTER TABLE public.accounts ADD COLUMN app_version TEXT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='accounts' AND column_name='lang_code') THEN
        ALTER TABLE public.accounts ADD COLUMN lang_code TEXT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='accounts' AND column_name='system_lang_code') THEN
        ALTER TABLE public.accounts ADD COLUMN system_lang_code TEXT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='accounts' AND column_name='is_premium') THEN
        ALTER TABLE public.accounts ADD COLUMN is_premium BOOLEAN DEFAULT FALSE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='accounts' AND column_name='register_time') THEN
        ALTER TABLE public.accounts ADD COLUMN register_time BIGINT;
    END IF;
END
$$;
"""

def _resolve_env_ref(value: str | None) -> str | None:
    """
    Если value похоже на имя переменной окружения (например, 'DATABASE_URL' или 'DB_USER'),
    подставляем её значение. Если это уже DSN postgres — возвращаем как есть.
    """
    if not value:
        return None
    v = value.strip()
    if v.lower().startswith(("postgres://", "postgresql://")):
        return v
    # трактуем как ссылку на другую переменную окружения
    return os.getenv(v)

def _connect_dsn(dsn: str):
    return psycopg2.connect(dsn)

def has_all_meta_columns(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='accounts'
        """)
        cols = {r[0] for r in cur.fetchall()}
        return all(c in cols for c in META_COLUMNS)

def bootstrap_accounts_privileges() -> str:
    """
    Под postgres:
      - проверяет наличие таблицы accounts
      - меняет владельца на PG_APP_OWNER
      - выдаёт права
      - добавляет недостающие мета-колонки (идемпотентно)
    DSN и owner берутся из:
      PG_BOOTSTRAP_DSN (может быть ссылкой на DATABASE_URL)
      PG_APP_OWNER     (может быть ссылкой на DB_USER)
    """
    raw_dsn = os.getenv("PG_BOOTSTRAP_DSN")
    raw_owner = os.getenv("PG_APP_OWNER", "tguser")

    dsn = _resolve_env_ref(raw_dsn)
    owner = _resolve_env_ref(raw_owner) or raw_owner

    if not dsn:
        return "PG_BOOTSTRAP_DSN not set/empty — skip"

    print(f"[BOOTSTRAP] using DSN={raw_dsn!r} -> resolved", flush=True)
    conn = _connect_dsn(dsn)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema='public' AND table_name='accounts'
            """)
            if cur.fetchone() is None:
                raise RuntimeError("Table public.accounts not found")

            cur.execute(f"ALTER TABLE public.accounts OWNER TO {owner};")
            cur.execute(f"GRANT ALL ON TABLE public.accounts TO {owner};")
            cur.execute(BOOTSTRAP_COLUMNS_SQL)

        conn.commit()
        return f"accounts: owner -> {owner}, columns ensured"
    except Exception as e:
        conn.rollback()
        return f"bootstrap error: {e}"
    finally:
        conn.close()
