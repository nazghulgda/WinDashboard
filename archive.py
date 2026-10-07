# archive.py - archiving and restoring tasks

import os
import json
import zipfile
import re
from datetime import datetime

from database import (
    get_task, get_checkpoints, get_notes, get_links,
    get_connection, delete_task, init_db
)
from config import ARCHIVE_DIR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_filename(text: str, max_len: int = 40) -> str:
    """Converts task title into a safe file name."""
    safe = re.sub(r'[^\w\s-]', '', text).strip()
    safe = re.sub(r'[\s]+', '_', safe)
    return safe[:max_len]


def _ensure_archive_dir():
    """Creates the archive folder if it does not exist."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_task_to_zip(task_id: int, source: str) -> str:
    """
    Archives task into a ZIP file and deletes it from the database.
    source: 'active' | 'onhold'
    Returns path of the created ZIP file.
    """
    _ensure_archive_dir()

    task   = get_task(task_id)
    if not task:
        raise ValueError(f"Task #{task_id} does not exist.")

    checkpoints = get_checkpoints(task_id)
    notes  = get_notes(task_id)
    links  = get_links(task_id)

    # JSON data
    data = {
        "meta": {
            "export_date":    datetime.now().isoformat(),
            "source":         source,          # 'active' | 'onhold'
            "app_version":    "1.0",
        },
        "task":   dict(task),
        "checkpoints": [dict(c) for c in checkpoints],
        "notes":  [dict(n) for n in notes],
        "links":  [dict(l) for l in links],
    }

    # README readable without the application
    done_checkpoints  = [c for c in checkpoints if c["completed"]]
    total_checkpoints = len(checkpoints)
    readme_lines = [
        f"TASK: {task['title']}",
        f"{'=' * 60}",
        f"ID:            {task['id']}",
        f"Description:   {task['description'] or '(none)'}",
        f"Created:       {task['created_at'][:16].replace('T', ' ')}",
        f"Archived:      {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Source:        {'On Hold' if source == 'onhold' else 'Active (finished)'}",
        f"Progress:      {len(done_checkpoints)}/{total_checkpoints} checkpoints",
        "",
        "CHECKPOINTS:",
        "-" * 40,
    ]
    for c in checkpoints:
        if c["checkpoint_type"] == "counter":
            status = f"x{c['iteration_count']}" if c["iteration_count"] > 0 else "[ ]"
        else:
            status = "[x]" if c["completed"] else "[ ]"
        readme_lines.append(f"  {status}  {c['checkpoint_order']:2}. {c['name']}")

    if notes:
        readme_lines += ["", "NOTES:", "-" * 40]
        for n in notes:
            readme_lines.append(f"  [{n['created_at'][:16].replace('T', ' ')}] {n['title']}")
            if n["content"]:
                for line in n["content"].split("\n")[:3]:
                    readme_lines.append(f"      {line}")
                if len(n["content"].split("\n")) > 3:
                    readme_lines.append("      ...")

    if links:
        readme_lines += ["", "LINKS:", "-" * 40]
        for l in links:
            icon = "[DIR]" if l["link_type"] == "folder" else "[FIL]"
            readme_lines.append(f"  {icon} {l['label']}: {l['path']}")

    readme_text = "\n".join(readme_lines)

    # ZIP file name
    date_str   = datetime.now().strftime("%Y-%m-%d")
    src_tag    = "onhold" if source == "onhold" else "finished"
    safe_title = _safe_filename(task["title"])
    zip_name   = f"task_{task['id']}_{src_tag}_{safe_title}_{date_str}.zip"
    zip_path   = os.path.join(ARCHIVE_DIR, zip_name)

    # Write ZIP
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("task.json",   json.dumps(data, ensure_ascii=False, indent=2))
        zf.writestr("README.txt",  readme_text)

    # Delete task from database
    delete_task(task_id)

    return zip_path


# ---------------------------------------------------------------------------
# Import / restore
# ---------------------------------------------------------------------------

def import_task_from_zip(zip_path: str) -> int:
    """
    Restores task from a ZIP file into the database.
    Returns new task id (may differ from the original one).
    """
    init_db()

    with zipfile.ZipFile(zip_path, "r") as zf:
        data = json.loads(zf.read("task.json").decode("utf-8"))

    task   = data["task"]
    # "stages" = key used by archives created before the checkpoint renaming
    checkpoints = data.get("checkpoints", data.get("stages", []))
    notes  = data["notes"]
    links  = data["links"]
    source = data["meta"].get("source", "active")

    with get_connection() as conn:
        # Insert task — on_hold according to the source
        on_hold    = 1 if source == "onhold" else 0
        on_hold_at = task.get("on_hold_at") if on_hold else None

        cur = conn.execute(
            """INSERT INTO tasks
               (title, description, on_hold, on_hold_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                task["title"],
                task.get("description", ""),
                on_hold,
                on_hold_at,
                task["created_at"],
                datetime.now().isoformat(),
            )
        )
        new_task_id = cur.lastrowid

        # Insert checkpoints (old archives use stage_order / stage_type keys)
        for c in checkpoints:
            conn.execute(
                """INSERT INTO task_checkpoints
                   (task_id, checkpoint_order, name, checkpoint_type, completed, iteration_count)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    new_task_id,
                    c["checkpoint_order"] if "checkpoint_order" in c else c["stage_order"],
                    c["name"],
                    c.get("checkpoint_type", c.get("stage_type", "check")),
                    c["completed"],
                    c.get("iteration_count", 0),
                )
            )

        # Insert notes
        for n in notes:
            conn.execute(
                """INSERT INTO task_notes
                   (task_id, title, content, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    new_task_id,
                    n["title"],
                    n.get("content", ""),
                    n["created_at"],
                    n["updated_at"],
                )
            )

        # Insert links
        for l in links:
            conn.execute(
                """INSERT INTO task_links
                   (task_id, label, path, link_type)
                   VALUES (?, ?, ?, ?)""",
                (new_task_id, l["label"], l["path"], l["link_type"])
            )

    return new_task_id


# ---------------------------------------------------------------------------
# Removing an archived task
# ---------------------------------------------------------------------------

def remove_archived_task(zip_path: str):
    """
    Moves the ZIP file to the 'removed' subfolder inside ARCHIVE_DIR.
    The file is not deleted permanently — it can be recovered manually.
    """
    removed_dir = os.path.join(ARCHIVE_DIR, "removed")
    os.makedirs(removed_dir, exist_ok=True)

    filename = os.path.basename(zip_path)
    dest = os.path.join(removed_dir, filename)

    # If a file with the same name already exists in removed — add a time suffix
    if os.path.exists(dest):
        base, ext = os.path.splitext(filename)
        dest = os.path.join(removed_dir, f"{base}_{datetime.now().strftime('%H%M%S')}{ext}")

    os.rename(zip_path, dest)


# ---------------------------------------------------------------------------
# Listing the archive
# ---------------------------------------------------------------------------

def list_archive() -> list[dict]:
    """
    Returns list of archived tasks from the ARCHIVE_DIR folder.
    Each item: {zip_path, filename, title, source, date, task_id_orig}
    """
    _ensure_archive_dir()
    result = []

    for fname in sorted(os.listdir(ARCHIVE_DIR), reverse=True):
        if not fname.endswith(".zip"):
            continue
        zip_path = os.path.join(ARCHIVE_DIR, fname)
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                data      = json.loads(zf.read("task.json").decode("utf-8"))
            meta   = data.get("meta", {})
            task   = data.get("task", {})
            checkpoints = data.get("checkpoints", data.get("stages", []))
            done   = sum(1 for c in checkpoints if c.get("completed"))
            total  = len(checkpoints)
            result.append({
                "zip_path":      zip_path,
                "filename":      fname,
                "title":         task.get("title", "?"),
                "description":   task.get("description", ""),
                "source":        meta.get("source", "active"),
                "export_date":   meta.get("export_date", "")[:16].replace("T", " "),
                "created_at":    task.get("created_at", "")[:10],
                "task_id_orig":  task.get("id"),
                "progress":      f"{done}/{total}",
            })
        except Exception:
            continue  # corrupted ZIP — skipped

    return result
