# database.py — database structure and CRUD functions

import os
import shutil
import sqlite3
from datetime import datetime
from config import DB_PATH, CHECKPOINTS, CHECKPOINT_GROUPS


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
        _migrate_legacy_stage_names(conn)
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

            CREATE TABLE IF NOT EXISTS task_checkpoints (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id         INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                checkpoint_order INTEGER NOT NULL,
                name            TEXT    NOT NULL,
                checkpoint_type TEXT    NOT NULL DEFAULT 'check',
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
        cp_cols = [r[1] for r in conn.execute("PRAGMA table_info(task_checkpoints)").fetchall()]
        if "checkpoint_type" not in cp_cols:
            conn.execute("ALTER TABLE task_checkpoints ADD COLUMN checkpoint_type TEXT NOT NULL DEFAULT 'check'")
        if "iteration_count" not in cp_cols:
            conn.execute("ALTER TABLE task_checkpoints ADD COLUMN iteration_count INTEGER NOT NULL DEFAULT 0")

        tasks_cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
        if "on_hold" not in tasks_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN on_hold INTEGER NOT NULL DEFAULT 0")
        if "on_hold_at" not in tasks_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN on_hold_at TEXT")


def _migrate_legacy_stage_names(conn):
    """Backward compatibility: renames the old 'task_stages' table and its
    'stage_order' / 'stage_type' columns to the checkpoint naming.
    Does nothing for a new database or one that is already migrated."""
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
    if "task_stages" in tables and "task_checkpoints" not in tables:
        conn.execute("ALTER TABLE task_stages RENAME TO task_checkpoints")
        tables.add("task_checkpoints")
    if "task_checkpoints" not in tables:
        return
    cols = [r[1] for r in conn.execute("PRAGMA table_info(task_checkpoints)").fetchall()]
    if "stage_order" in cols and "checkpoint_order" not in cols:
        conn.execute("ALTER TABLE task_checkpoints RENAME COLUMN stage_order TO checkpoint_order")
    if "stage_type" in cols and "checkpoint_type" not in cols:
        conn.execute("ALTER TABLE task_checkpoints RENAME COLUMN stage_type TO checkpoint_type")


# ---------------------------------------------------------------------------
# TASKS
# ---------------------------------------------------------------------------

def create_task(title: str, description: str = "", checkpoints: list = None) -> int:
    """Creates new task.
    checkpoints=None  -> default checkpoints from config.CHECKPOINTS
    checkpoints=[]    -> empty kanban (no checkpoints)
    checkpoints=[...] -> given list of checkpoints in config.CHECKPOINTS format
    """
    checkpoints_to_use = CHECKPOINTS if checkpoints is None else checkpoints

    now = datetime.now().isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (title, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (title, description, now, now)
        )
        task_id = cur.lastrowid
        if checkpoints_to_use:
            conn.executemany(
                """INSERT INTO task_checkpoints
                   (task_id, checkpoint_order, name, checkpoint_type, completed, iteration_count)
                   VALUES (?, ?, ?, ?, 0, 0)""",
                [(task_id, c["order"], c["name"], c.get("type", "check")) for c in checkpoints_to_use]
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
    """Returns last activity date in task (task + checkpoints + notes)."""
    with get_connection() as conn:
        task_upd = conn.execute(
            "SELECT updated_at FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        note_upd = conn.execute(
            "SELECT MAX(updated_at) FROM task_notes WHERE task_id = ?", (task_id,)
        ).fetchone()
        # Checkpoints do not have updated_at — used updated_at from task (updated with toggle)
        dates = [
            task_upd[0] if task_upd else None,
            note_upd[0] if note_upd else None,
        ]
        dates = [d for d in dates if d]
    return max(dates) if dates else ""


def backup_db():
    """Creates a backup copy of the database (tasks.db.bak).
    Replaces the previous copy. Silent on error."""
    if not os.path.exists(DB_PATH):
        return
    backup_path = DB_PATH + ".bak"
    try:
        if os.path.exists(backup_path):
            os.remove(backup_path)
        shutil.copy2(DB_PATH, backup_path)
    except Exception:
        pass


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


def set_checkpoint_completed(checkpoint_id: int, completed: bool):
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


def set_iteration_count(checkpoint_id: int, count: int):
    """Sets checkpoint iteration counter. count >= 0."""
    count = max(0, count)
    completed = 1 if count > 0 else 0
    with get_connection() as conn:
        conn.execute(
            "UPDATE task_checkpoints SET iteration_count = ?, completed = ? WHERE id = ?",
            (count, completed, checkpoint_id)
        )
        task_id = conn.execute(
            "SELECT task_id FROM task_checkpoints WHERE id = ?", (checkpoint_id,)
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
    """Returns actual status name of task based on CHECKPOINT_GROUPS."""
    checkpoints = get_checkpoints(task_id)
    completed_orders = {c["checkpoint_order"] for c in checkpoints if c["completed"]}

    current_status = CHECKPOINT_GROUPS[0]["name"]  # "Not started"
    for group in CHECKPOINT_GROUPS:
        if not group["checkpoints"]:
            continue
        if all(order in completed_orders for order in group["checkpoints"]):
            current_status = group["name"]

    return current_status


def add_checkpoint(task_id: int, name: str, checkpoint_type: str = "check") -> int:
    """Adds a new checkpoint at the end of the kanban list of the task."""
    now = datetime.now().isoformat()
    with get_connection() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(checkpoint_order), 0) FROM task_checkpoints WHERE task_id = ?",
            (task_id,)
        ).fetchone()[0]
        cur = conn.execute(
            """INSERT INTO task_checkpoints
               (task_id, checkpoint_order, name, checkpoint_type, completed, iteration_count)
               VALUES (?, ?, ?, ?, 0, 0)""",
            (task_id, max_order + 1, name, checkpoint_type)
        )
        conn.execute(
            "UPDATE tasks SET updated_at = ? WHERE id = ?", (now, task_id)
        )
    return cur.lastrowid


def delete_checkpoint(checkpoint_id: int):
    """Deletes a checkpoint and renumbers the remaining checkpoints of the task."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT task_id, checkpoint_order FROM task_checkpoints WHERE id = ?", (checkpoint_id,)
        ).fetchone()
        if not row:
            return
        task_id, deleted_order = row[0], row[1]
        conn.execute("DELETE FROM task_checkpoints WHERE id = ?", (checkpoint_id,))
        # Shift down all checkpoints above the deleted one
        conn.execute(
            "UPDATE task_checkpoints SET checkpoint_order = checkpoint_order - 1 "
            "WHERE task_id = ? AND checkpoint_order > ?",
            (task_id, deleted_order)
        )
        conn.execute(
            "UPDATE tasks SET updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), task_id)
        )


def update_checkpoint(checkpoint_id: int, name: str, checkpoint_type: str):
    """Updates name and type of a checkpoint."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE task_checkpoints SET name = ?, checkpoint_type = ? WHERE id = ?",
            (name, checkpoint_type, checkpoint_id)
        )
        task_id = conn.execute(
            "SELECT task_id FROM task_checkpoints WHERE id = ?", (checkpoint_id,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE tasks SET updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), task_id)
        )


def move_checkpoint(task_id: int, checkpoint_id: int, direction: str):
    """Moves a checkpoint up ('up') or down ('down') by swapping checkpoint_order with its neighbour."""
    with get_connection() as conn:
        current = conn.execute(
            "SELECT checkpoint_order FROM task_checkpoints WHERE id = ?", (checkpoint_id,)
        ).fetchone()
        if not current:
            return
        current_order = current[0]
        target_order = current_order - 1 if direction == "up" else current_order + 1

        neighbor = conn.execute(
            "SELECT id FROM task_checkpoints WHERE task_id = ? AND checkpoint_order = ?",
            (task_id, target_order)
        ).fetchone()
        if not neighbor:
            return  # already at the edge of the list

        conn.execute(
            "UPDATE task_checkpoints SET checkpoint_order = ? WHERE id = ?",
            (target_order, checkpoint_id)
        )
        conn.execute(
            "UPDATE task_checkpoints SET checkpoint_order = ? WHERE id = ?",
            (current_order, neighbor[0])
        )
        conn.execute(
            "UPDATE tasks SET updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), task_id)
        )


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
