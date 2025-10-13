#!/usr/bin/env bash
set -euo pipefail

DB_NAME="tgdb"

run_sql() {
  sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 "$@"
}



# 1) Таблица логов и индексы
run_sql <<'SQL'
CREATE TABLE IF NOT EXISTS public.comment_check_log (
    id          BIGSERIAL PRIMARY KEY,
    task_id     BIGINT NOT NULL REFERENCES public.tasks(id) ON DELETE CASCADE,
    account_id  BIGINT REFERENCES public.accounts(id) ON DELETE SET NULL,
    channel     TEXT   NOT NULL,
    can_comment BOOLEAN,
    mode        TEXT,
    message     TEXT,
    checked_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_comment_check_log_task
  ON public.comment_check_log(task_id);

CREATE INDEX IF NOT EXISTS idx_comment_check_log_task_channel
  ON public.comment_check_log(task_id, channel);
SQL

# 2) Индекс на tasks(type)
run_sql <<'SQL' || true
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE schemaname='public' AND indexname='idx_tasks_type'
  ) THEN
    EXECUTE 'CREATE INDEX idx_tasks_type ON public.tasks(type)';
  END IF;
EXCEPTION
  WHEN insufficient_privilege THEN
    RAISE NOTICE 'Skip idx_tasks_type: insufficient privileges';
  WHEN undefined_table THEN
    RAISE NOTICE 'Skip idx_tasks_type: table public.tasks not found';
END$$;
SQL

echo "✅ Migration applied."