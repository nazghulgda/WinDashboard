# database.py — database structure and CRUD functions

import sqlite3
from datetime import datetime
from config import DB_PATH, STAGES, STAGE_GROUPS


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------

def init_db():
    """Creates tables in not exists. Migrates for existing databases."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT    NOT NULL,
                description TEXT    DEFAULT '',
                on_hold     INTEGER NOT NULL DEFAULT 0,
                on_hold_at  TEXT,
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_stages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id         INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                stage_order     INTEGER NOT NULL,
                name            TEXT    NOT NULL,
                stage_type      TEXT    NOT NULL DEFAULT 'check',
                completed       INTEGER NOT NULL DEFAULT 0,
                iteration_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS task_notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                title       TEXT    NOT NULL,
                content     TEXT    DEFAULT '',
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_links (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                label       TEXT    NOT NULL,
                path        TEXT    NOT NULL,
                link_type   TEXT    NOT NULL DEFAULT 'file'
            );
        """)

        # Migration for existing databases
        stages_cols = [r[1] for r in conn.execute("PRAGMA table_info(task_stages)").fetchall()]
        if "stage_type" not in stages_cols:
            conn.execute("ALTER TABLE task_stages ADD COLUMN stage_type TEXT NOT NULL DEFAULT 'check'")
        if "iteration_count" not in stages_cols:
            conn.execute("ALTER TABLE task_stages ADD COLUMN iteration_count INTEGER NOT NULL DEFAULT 0")

        tasks_cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
        if "on_hold" not in tasks_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN on_hold INTEGER NOT NULL DEFAULT 0")
        if "on_hold_at" not in tasks_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN on_hold_at TEXT")


# ---------------------------------------------------------------------------
# TASKS
# ---------------------------------------------------------------------------

def create_task(title: str, description: str = "") -> int:
    """Creates new task with stages from config.STAGES."""
    now = datetime.now().isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (title, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (title, description, now, now)
        )
        task_id = cur.lastrowid
        conn.executemany(
            """INSERT INTO task_stages
               (task_id, stage_order, name, stage_type, completed, iteration_count)
               VALUES (?, ?, ?, ?, 0, 0)""",
            [(task_id, s["order"], s["name"], s.get("type", "check")) for s in STAGES]
        )
    return task_id


def get_all_tasks() -> list:
    """Returns active tasks sorted by newest."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE on_hold = 0 ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_on_hold_tasks() -> list:
    """Returns holded tasks sorted by lastest holded."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE on_hold = 1 ORDER BY on_hold_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_task(task_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(row) if row else None


def update_task(task_id: int, title: str, description: str):
    now = datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE tasks SET title = ?, description = ?, updated_at = ? WHERE id = ?",
            (title, description, now, task_id)
        )


def delete_task(task_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


def set_on_hold(task_id: int, on_hold: bool):
    now = datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE tasks SET on_hold = ?, on_hold_at = ?, updated_at = ? WHERE id = ?",
            (1 if on_hold else 0, now if on_hold else None, now, task_id)
        )


def get_last_activity(task_id: int) -> str:
    """Returns last activity date in task (task + stages + notes + links)."""
    with get_connection() as conn:
        task_upd = conn.execute(
            "SELECT updated_at FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        note_upd = conn.execute(
            "SELECT MAX(updated_at) FROM task_notes WHERE task_id = ?", (task_id,)
        ).fetchone()
        # Stages does not have updated_at — used updated_at from task (updated with toggle)
        dates = [
            task_upd[0] if task_upd else None,
            note_upd[0] if note_upd else None,
        ]
        dates = [d for d in dates if d]
    return max(dates) if dates else ""


# ---------------------------------------------------------------------------
# TASK CHECKPOINTS
# ---------------------------------------------------------------------------

def get_checkpoints(task_id: int) -> list:
    """Returns checkpoints of particular task in order."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM task_checkpoints WHERE task_id = ? ORDER BY checkpoint_order",
            (task_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def set_checkpoint_completed(stage_id: int, completed: bool):
    """Sets state of checkbox of checkpoint and updates updated_at of task."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE task_checkpoints SET completed = ? WHERE id = ?",
            (1 if completed else 0, checkpoint_id)
        )
        # Update updated_at of task for get_last_activity detection
        task_id = conn.execute(
            "SELECT task_id FROM task_checkpoints WHERE id = ?", (checkpoint_id,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE tasks SET updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), task_id)
        )


def set_iteration_count(stage_id: int, count: int):
    """Sets checkpoint iteration counter. count >= 0."""
    count = max(0, count)
    completed = 1 if count > 0 else 0
    with get_connection() as conn:
        conn.execute(
            "UPDATE task_checkpoints SET iteration_count = ?, completed = ? WHERE id = ?",
            (count, completed, checkpoint_id)
        )
        task_id = conn.execute(
            "SELECT task_id FROM task_checkpoints WHERE id = ?", (stage_id,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE tasks SET updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), task_id)
        )


def get_task_progress(task_id: int) -> tuple[int, int]:
    """Returns (finished, all) task checkpoints."""
    with get_connection() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM task_checkpoints WHERE task_id = ?", (task_id,)
        ).fetchone()[0]
        done = conn.execute(
            "SELECT COUNT(*) FROM task_checkpoints WHERE task_id = ? AND completed = 1", (task_id,)
        ).fetchone()[0]
    return done, total


def get_task_checkpoint_status(task_id: int) -> str:
    """Returns actual status name from task based on CHECKPOINT_GROUPS."""
    checkpoints = get_checkpoints(task_id)
    completed_orders = {s["checkpoint_order"] for s in checkpoints if s["completed"]}

    current_status = CHECKPOINT_GROUPS[0]["name"]  # "Not started"
    for group in CEHCKPOINT_GROUPS:
        if not group["checkpoints"]:
            continue
        if all(order in completed_orders for order in group["checkpoints"]):
            current_status = group["name"]

    return current_status


# ---------------------------------------------------------------------------
# TASK NOTES
# ---------------------------------------------------------------------------

def create_note(task_id: int, title: str, content: str = "") -> int:
    now = datetime.now().isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO task_notes (task_id, title, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (task_id, title, content, now, now)
        )
    return cur.lastrowid


def get_notes(task_id: int) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM task_notes WHERE task_id = ? ORDER BY created_at DESC",
            (task_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def update_note(note_id: int, title: str, content: str):
    now = datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE task_notes SET title = ?, content = ?, updated_at = ? WHERE id = ?",
            (title, content, now, note_id)
        )


def delete_note(note_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM task_notes WHERE id = ?", (note_id,))


# ---------------------------------------------------------------------------
# TASK LINKS
# ---------------------------------------------------------------------------

def create_link(task_id: int, label: str, path: str, link_type: str = "file") -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO task_links (task_id, label, path, link_type) VALUES (?, ?, ?, ?)",
            (task_id, label, path, link_type)
        )
    return cur.lastrowid


def get_links(task_id: int) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM task_links WHERE task_id = ?", (task_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def update_link(link_id: int, label: str, path: str, link_type: str):
    with get_connection() as conn:
        conn.execute(
            "UPDATE task_links SET label = ?, path = ?, link_type = ? WHERE id = ?",
            (label, path, link_type, link_id)
        )


def delete_link(link_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM task_links WHERE id = ?", (link_id,))
