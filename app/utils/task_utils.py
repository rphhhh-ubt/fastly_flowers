from datetime import datetime
from app.db import get_connection
from psycopg2.extras import RealDictCursor
import psycopg2

def update_task_status(task_id, status, result=None):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE tasks
                SET status = %s, result = %s, updated_at = NOW()
                WHERE id = %s
            """, (status, result, task_id))
        conn.commit()
    finally:
        conn.close()

async def claim_one_task():
    conn = None
    task = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                UPDATE tasks
                SET status = 'processing', updated_at = NOW()
                WHERE id = (
                    SELECT id FROM tasks
                    WHERE status = 'pending' AND is_active = TRUE AND scheduled_at <= NOW() AND is_master = FALSE
                    ORDER BY scheduled_at ASC, created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING *;
            """)
            task = cur.fetchone()
            if task:
                conn.commit()
            else:
                conn.rollback()
    except psycopg2.Error as e:
        print(f"[DB Error] Ошибка при захвате задачи: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
    return task
