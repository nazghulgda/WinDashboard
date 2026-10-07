# database.py — database structure and CRUD functions

import os
import re
import shutil
import sqlite3
from datetime import datetime
from config import (DB_PATH, ATTACHMENTS_DIR, CHECKPOINTS, CHECKPOINT_GROUPS,
                    DEFAULT_CHECKPOINT, STATUS_IN_PROGRESS)

# Application data folder — attachment paths are stored relative to it
APP_DIR = os.path.dirname(os.path.abspath(DB_PATH))

# Last working copy of the database
LAST_WORKING_PATH = DB_PATH + ".bak"


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
                iteration_count INTEGER NOT NULL DEFAULT 0,
                template_order  INTEGER
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

            CREATE TABLE IF NOT EXISTS task_attachments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                filename    TEXT    NOT NULL,
                stored_path TEXT    NOT NULL,
                deleted     INTEGER NOT NULL DEFAULT 0,
                added_at    TEXT    NOT NULL
            );
        """)

        # Migration for existing databases
        cp_cols = [r[1] for r in conn.execute("PRAGMA table_info(task_checkpoints)").fetchall()]
        if "checkpoint_type" not in cp_cols:
            conn.execute("ALTER TABLE task_checkpoints ADD COLUMN checkpoint_type TEXT NOT NULL DEFAULT 'check'")
        if "iteration_count" not in cp_cols:
            conn.execute("ALTER TABLE task_checkpoints ADD COLUMN iteration_count INTEGER NOT NULL DEFAULT 0")
        if "template_order" not in cp_cols:
            conn.execute("ALTER TABLE task_checkpoints ADD COLUMN template_order INTEGER")
            # Existing checkpoints are matched with the template by name
            conn.executemany(
                "UPDATE task_checkpoints SET template_order = ? WHERE name = ?",
                [(c["order"], c["name"]) for c in CHECKPOINTS]
            )

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
# Database check and last working copy
# ---------------------------------------------------------------------------

def check_db(path: str = DB_PATH) -> bool:
    """Checks if the database file can be opened and its structure is not damaged."""
    try:
        conn = sqlite3.connect(path)
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
        finally:
            conn.close()
        return bool(row) and row[0] == "ok"
    except Exception:
        return False


def backup_db() -> bool:
    """Saves the database as the last working copy (tasks.db.bak).
    Only a database which passes the check is copied, so a damaged
    database never replaces a good copy. Returns True if the copy was saved."""
    if not os.path.exists(DB_PATH) or not check_db():
        return False
    tmp_path = LAST_WORKING_PATH + ".tmp"
    try:
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(tmp_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        os.replace(tmp_path, LAST_WORKING_PATH)
        return True
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return False


def verify_db() -> str:
    """Checks the database and restores it from the last working copy if it is damaged.
    Returns:
      "ok"       — database is fine (or does not exist yet and there is no copy)
      "restored" — database was damaged or missing and was restored from the last working copy
      "failed"   — database is damaged and there is no working copy to restore from
    The damaged file is never deleted — it is kept as tasks.db.corrupt_<date>_<time>."""
    has_db   = os.path.exists(DB_PATH)
    has_copy = os.path.exists(LAST_WORKING_PATH) and os.path.getsize(LAST_WORKING_PATH) > 0

    if has_db:
        # Empty file is a valid empty database for SQLite — treat it as damaged when a copy exists
        emptied = os.path.getsize(DB_PATH) == 0 and has_copy
        if not emptied and check_db():
            return "ok"
    elif not has_copy:
        return "ok"

    if not has_copy or not check_db(LAST_WORKING_PATH):
        return "failed"

    try:
        if has_db:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            os.replace(DB_PATH, f"{DB_PATH}.corrupt_{stamp}")
        shutil.copy2(LAST_WORKING_PATH, DB_PATH)
    except Exception:
        return "failed"
    return "restored" if check_db() else "failed"


def _touch_task(conn, task_id: int):
    """Marks activity in the task — every change inside a task updates its updated_at."""
    conn.execute(
        "UPDATE tasks SET updated_at = ? WHERE id = ?",
        (datetime.now().isoformat(), task_id)
    )


# ---------------------------------------------------------------------------
# TASKS
# ---------------------------------------------------------------------------

def create_task(title: str, description: str = "", checkpoints: list = None) -> int:
    """Creates new task.
    checkpoints=None  -> default checkpoints from config.CHECKPOINTS
    checkpoints=[]    -> empty kanban (config.DEFAULT_CHECKPOINT only)
    checkpoints=[...] -> given list of checkpoints in config.CHECKPOINTS format
    """
    from_template = checkpoints is None
    checkpoints_to_use = CHECKPOINTS if from_template else (checkpoints or [DEFAULT_CHECKPOINT])

    now = datetime.now().isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (title, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (title, description, now, now)
        )
        task_id = cur.lastrowid
        # template_order binds a checkpoint to config.CHECKPOINT_GROUPS — only for the template
        conn.executemany(
            """INSERT INTO task_checkpoints
               (task_id, checkpoint_order, name, checkpoint_type, completed, iteration_count,
                template_order)
               VALUES (?, ?, ?, ?, 0, 0, ?)""",
            [(task_id, c["order"], c["name"], c.get("type", "check"),
              c["order"] if from_template else None) for c in checkpoints_to_use]
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
    """Returns last activity date in task.
    Every change in a task (checkpoints, notes, links, attachments) updates updated_at of the task."""
    with get_connection() as conn:
        task_upd = conn.execute(
            "SELECT updated_at FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        note_upd = conn.execute(
            "SELECT MAX(updated_at) FROM task_notes WHERE task_id = ?", (task_id,)
        ).fetchone()
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
    """Returns actual status name of task.

    No checkpoint completed   -> name of the first group in CHECKPOINT_GROUPS
    All checkpoints completed -> name of the last group in CHECKPOINT_GROUPS
    Otherwise                 -> name of the last group completed in a row; groups are bound
                                 to checkpoints from the template (template_order), not to
                                 their current position, so moving, adding or deleting
                                 checkpoints does not change the meaning of a group.
    Task without template checkpoints, or with no group completed yet -> STATUS_IN_PROGRESS."""
    checkpoints = get_checkpoints(task_id)
    done = sum(1 for c in checkpoints if c["completed"])

    if done == 0:
        return CHECKPOINT_GROUPS[0]["name"]
    if done == len(checkpoints):
        return CHECKPOINT_GROUPS[-1]["name"]

    completed = {c["template_order"]: bool(c["completed"])
                 for c in checkpoints if c["template_order"] is not None}

    current_status = STATUS_IN_PROGRESS
    for group in CHECKPOINT_GROUPS[:-1]:
        # Checkpoints of the group which still exist in this task
        present = [order for order in group["checkpoints"] if order in completed]
        if not present:
            continue
        if not all(completed[order] for order in present):
            break
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


def delete_checkpoint(checkpoint_id: int) -> bool:
    """Deletes a checkpoint and renumbers the remaining checkpoints of the task.
    The last checkpoint of a task can not be deleted. Returns True if deleted."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT task_id, checkpoint_order FROM task_checkpoints WHERE id = ?", (checkpoint_id,)
        ).fetchone()
        if not row:
            return False
        task_id, deleted_order = row[0], row[1]
        count = conn.execute(
            "SELECT COUNT(*) FROM task_checkpoints WHERE task_id = ?", (task_id,)
        ).fetchone()[0]
        if count <= 1:
            return False
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
    return True


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
        _touch_task(conn, task_id)
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
        row = conn.execute(
            "SELECT task_id FROM task_notes WHERE id = ?", (note_id,)
        ).fetchone()
        if row:
            _touch_task(conn, row[0])


# ---------------------------------------------------------------------------
# TASK LINKS
# ---------------------------------------------------------------------------

def create_link(task_id: int, label: str, path: str, link_type: str = "file") -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO task_links (task_id, label, path, link_type) VALUES (?, ?, ?, ?)",
            (task_id, label, path, link_type)
        )
        _touch_task(conn, task_id)
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
        row = conn.execute(
            "SELECT task_id FROM task_links WHERE id = ?", (link_id,)
        ).fetchone()
        if row:
            _touch_task(conn, row[0])


def delete_link(link_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT task_id FROM task_links WHERE id = ?", (link_id,)
        ).fetchone()
        conn.execute("DELETE FROM task_links WHERE id = ?", (link_id,))
        if row:
            _touch_task(conn, row[0])


# ---------------------------------------------------------------------------
# TASK ATTACHMENTS
# ---------------------------------------------------------------------------
# Attachment = copy of a file kept in ATTACHMENTS_DIR/<task_id>_<task title>/.
# stored_path is relative to the application folder and always uses "/",
# so the whole folder can be moved or restored from a backup in another place.

def get_attachment_dir(task_id: int, task_title: str) -> str:
    """Returns path of the attachments folder of the task."""
    safe_title = re.sub(r'[^\w\s-]', '', task_title).strip()
    safe_title = re.sub(r'[\s]+', '_', safe_title)[:40]
    return os.path.join(ATTACHMENTS_DIR, f"{task_id}_{safe_title}")


def to_stored_path(path: str) -> str:
    """Converts file path into the form kept in the database."""
    return os.path.relpath(path, APP_DIR).replace("\\", "/")


def resolve_attachment_path(stored_path: str) -> str:
    """Returns full path of an attachment file from its stored_path."""
    if os.path.isabs(stored_path):
        return stored_path
    return os.path.join(APP_DIR, *stored_path.split("/"))


def create_attachment(task_id: int, filename: str, path: str) -> int:
    """Registers new attachment. The file has to be already copied to path."""
    now = datetime.now().isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO task_attachments (task_id, filename, stored_path, deleted, added_at)
               VALUES (?, ?, ?, 0, ?)""",
            (task_id, filename, to_stored_path(path), now)
        )
        _touch_task(conn, task_id)
    return cur.lastrowid


def get_attachments(task_id: int, include_deleted: bool = False) -> list:
    """Returns attachments of the task. include_deleted=True returns deleted ones as well."""
    query = "SELECT * FROM task_attachments WHERE task_id = ?"
    if not include_deleted:
        query += " AND deleted = 0"
    with get_connection() as conn:
        rows = conn.execute(query + " ORDER BY added_at", (task_id,)).fetchall()
    return [dict(r) for r in rows]


def soft_delete_attachment(att_id: int, new_path: str):
    """Marks attachment as deleted. new_path = place of the file after moving it
    to the 'deleted' subfolder."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT task_id FROM task_attachments WHERE id = ?", (att_id,)
        ).fetchone()
        if not row:
            return
        conn.execute(
            "UPDATE task_attachments SET deleted = 1, stored_path = ? WHERE id = ?",
            (to_stored_path(new_path), att_id)
        )
        _touch_task(conn, row[0])
