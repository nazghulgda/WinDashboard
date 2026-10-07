# backup.py — full backup of the application data

import os
import json
import sqlite3
import tempfile
import zipfile
from datetime import datetime

from config import DB_PATH, ARCHIVE_DIR, ATTACHMENTS_DIR, APP_VERSION

# Backups folder — next to the database
APP_DIR    = os.path.dirname(os.path.abspath(DB_PATH))
BACKUP_DIR = os.path.join(APP_DIR, "backups")


# ---------------------------------------------------------------------------
# Main backup function
# ---------------------------------------------------------------------------

def create_backup(progress_callback=None) -> str:
    """
    Creates full backup of the application as a ZIP file.
    Collects: database, database backup copy, attachments, tasks archives.
    Returns path of the created ZIP file.

    progress_callback: optional function(name: str, current: int, total: int)
    called while files are packed.
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    zip_name  = f"WinDashboard_backup_{timestamp}.zip"
    zip_path  = os.path.join(BACKUP_DIR, zip_name)

    # Collect list of files to pack
    files_to_pack = _collect_files()
    total = len(files_to_pack)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED,
                         allowZip64=True) as zf:
        # Backup metadata
        meta = _build_meta(total)
        meta_bytes = json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")
        zf.writestr("backup_meta.json", meta_bytes)

        for i, (src_path, arc_name) in enumerate(files_to_pack, 1):
            if progress_callback:
                progress_callback(arc_name, i, total)
            try:
                zf.write(src_path, arc_name)
            except Exception:
                pass  # file not available — skip, do not break

    return zip_path


def _collect_files() -> list[tuple[str, str]]:
    """
    Returns list of (source_path, name_in_archive) for all files
    included in the backup.
    Names in archive always use "/" as separator.
    """
    files = []

    # Database
    if os.path.exists(DB_PATH):
        files.append((DB_PATH, "tasks.db"))

    # Database backup copy
    bak_path = DB_PATH + ".bak"
    if os.path.exists(bak_path):
        files.append((bak_path, "tasks.db.bak"))

    # Attachments — whole folder structure
    if os.path.exists(ATTACHMENTS_DIR):
        for root, _, fnames in os.walk(ATTACHMENTS_DIR):
            for fname in fnames:
                src = os.path.join(root, fname)
                rel = os.path.relpath(src, APP_DIR)
                files.append((src, rel.replace("\\", "/")))

    # Tasks archives — archive/ folder
    if os.path.exists(ARCHIVE_DIR):
        for fname in os.listdir(ARCHIVE_DIR):
            if not fname.endswith(".zip"):
                continue
            src = os.path.join(ARCHIVE_DIR, fname)
            files.append((src, f"archive/{fname}"))

        # removed/ subfolder goes to backup as well
        removed_dir = os.path.join(ARCHIVE_DIR, "removed")
        if os.path.exists(removed_dir):
            for fname in os.listdir(removed_dir):
                src = os.path.join(removed_dir, fname)
                if os.path.isfile(src):
                    files.append((src, f"archive/removed/{fname}"))

    return files


def _build_meta(file_count: int) -> dict:
    """Builds backup metadata dictionary."""
    from database import get_all_tasks, get_on_hold_tasks
    try:
        active  = len(get_all_tasks())
        on_hold = len(get_on_hold_tasks())
    except Exception:
        active = on_hold = 0

    archive_count = 0
    if os.path.exists(ARCHIVE_DIR):
        archive_count = len([f for f in os.listdir(ARCHIVE_DIR)
                             if f.endswith(".zip")])

    att_count = 0
    if os.path.exists(ATTACHMENTS_DIR):
        for _, _, fnames in os.walk(ATTACHMENTS_DIR):
            att_count += len(fnames)

    return {
        "backup_date":      datetime.now().isoformat(),
        "app_version":      APP_VERSION,
        "tasks_active":     active,
        "tasks_on_hold":    on_hold,
        "tasks_archived":   archive_count,
        "attachment_files": att_count,
        "packed_files":     file_count,
    }


# ---------------------------------------------------------------------------
# Listing existing backups
# ---------------------------------------------------------------------------

def list_backups() -> list[dict]:
    """
    Returns list of existing backups sorted by newest.
    Each item: {zip_path, filename, date, size_mb, meta}
    """
    if not os.path.exists(BACKUP_DIR):
        return []

    result = []
    for fname in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if not fname.endswith(".zip"):
            continue
        zip_path = os.path.join(BACKUP_DIR, fname)
        size_mb  = os.path.getsize(zip_path) / (1024 * 1024)
        meta     = {}
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                if "backup_meta.json" in zf.namelist():
                    meta = json.loads(zf.read("backup_meta.json").decode("utf-8"))
        except Exception:
            pass
        result.append({
            "zip_path":  zip_path,
            "filename":  fname,
            "size_mb":   round(size_mb, 2),
            "meta":      meta,
            "date":      meta.get("backup_date", "")[:16].replace("T", "  "),
        })
    return result


# ---------------------------------------------------------------------------
# Restoring a backup
# ---------------------------------------------------------------------------

def restore_backup(zip_path: str) -> dict:
    """
    Restores a backup by merging it with the current data.
    Tasks and archived tasks which are missing now are added from the backup;
    nothing existing is changed or removed. A task is recognized by its title
    and creation date, so a task which exists now (active, on hold or archived)
    is never added for the second time.
    Returns: {tasks_added, tasks_skipped, archives_added}
    """
    from database import init_db, get_connection
    from archive import insert_task_data

    init_db()
    result = {"tasks_added": 0, "tasks_skipped": 0, "archives_added": 0}

    # Tasks known now: in the database and in the archive folder
    with get_connection() as conn:
        known = {(r[0], r[1]) for r in conn.execute("SELECT title, created_at FROM tasks")}
    if os.path.exists(ARCHIVE_DIR):
        for fname in os.listdir(ARCHIVE_DIR):
            if fname.endswith(".zip"):
                key = _archived_task_key(os.path.join(ARCHIVE_DIR, fname))
                if key:
                    known.add(key)

    with tempfile.TemporaryDirectory() as tmp_dir, zipfile.ZipFile(zip_path, "r") as zf:
        names = set(zf.namelist())

        # Tasks from the database of the backup
        if "tasks.db" in names:
            db_copy = os.path.join(tmp_dir, "tasks.db")
            with zf.open("tasks.db") as src, open(db_copy, "wb") as dst:
                dst.write(src.read())

            def open_attachment(att: dict):
                arc_name = att["stored_path"].replace("\\", "/")
                return zf.open(arc_name) if arc_name in names else None

            for data in _read_tasks(db_copy):
                key = (data["task"]["title"], data["task"]["created_at"])
                if key in known:
                    result["tasks_skipped"] += 1
                    continue
                insert_task_data(data, bool(data["task"].get("on_hold")), open_attachment)
                known.add(key)
                result["tasks_added"] += 1

        # Archived tasks
        for name in sorted(names):
            if not name.startswith("archive/") or not name.endswith(".zip"):
                continue
            if name.startswith("archive/removed/"):
                continue  # removed from the archive on purpose
            fname = os.path.basename(name)
            dest  = os.path.join(ARCHIVE_DIR, fname)
            if os.path.exists(dest):
                continue
            tmp_zip = os.path.join(tmp_dir, fname)
            with zf.open(name) as src, open(tmp_zip, "wb") as dst:
                dst.write(src.read())
            key = _archived_task_key(tmp_zip)
            if key is None or key in known:
                continue
            os.makedirs(ARCHIVE_DIR, exist_ok=True)
            os.replace(tmp_zip, dest)
            known.add(key)
            result["archives_added"] += 1

    return result


def _archived_task_key(zip_path: str):
    """Returns (title, created_at) of a task archived in the ZIP file, None if not readable."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            task = json.loads(zf.read("task.json").decode("utf-8")).get("task", {})
        return (task["title"], task["created_at"])
    except Exception:
        return None


def _read_tasks(db_path: str) -> list[dict]:
    """Reads all tasks from a database file into the format of task.json.
    Handles databases created before the checkpoint renaming as well."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        cp_table = "task_checkpoints" if "task_checkpoints" in tables else "task_stages"

        def rows(table: str, task_id: int) -> list[dict]:
            if table not in tables:
                return []
            return [dict(r) for r in conn.execute(
                f"SELECT * FROM {table} WHERE task_id = ? ORDER BY id", (task_id,))]

        result = []
        for task in conn.execute("SELECT * FROM tasks ORDER BY id"):
            task = dict(task)
            result.append({
                "task":        task,
                "checkpoints": rows(cp_table, task["id"]),
                "notes":       rows("task_notes", task["id"]),
                "links":       rows("task_links", task["id"]),
                "attachments": rows("task_attachments", task["id"]),
            })
        return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Deleting old backups
# ---------------------------------------------------------------------------

def delete_backup(zip_path: str):
    """Deletes backup file. Can not be undone."""
    if os.path.exists(zip_path):
        os.remove(zip_path)
