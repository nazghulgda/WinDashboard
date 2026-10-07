# backup.py — full backup of the application data

import os
import json
import zipfile
from datetime import datetime

from config import DB_PATH, ARCHIVE_DIR

# Backups folder — next to the database
APP_DIR    = os.path.dirname(os.path.abspath(DB_PATH))
BACKUP_DIR = os.path.join(APP_DIR, "backups")


# ---------------------------------------------------------------------------
# Main backup function
# ---------------------------------------------------------------------------

def create_backup(progress_callback=None) -> str:
    """
    Creates full backup of the application as a ZIP file.
    Collects: database, database backup copy, tasks archives.
    Returns path of the created ZIP file.

    progress_callback: optional function(name: str, current: int, total: int)
    called while files are packed.
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
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

    return {
        "backup_date":    datetime.now().isoformat(),
        "app_version":    "1.0",
        "tasks_active":   active,
        "tasks_on_hold":  on_hold,
        "tasks_archived": archive_count,
        "packed_files":   file_count,
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
# Deleting old backups
# ---------------------------------------------------------------------------

def delete_backup(zip_path: str):
    """Deletes backup file. Can not be undone."""
    if os.path.exists(zip_path):
        os.remove(zip_path)
