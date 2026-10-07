# archive.py - archiving and restoring tasks

import os
import json
import zipfile
import re
import shutil
from datetime import datetime

from database import (
    get_task, get_checkpoints, get_notes, get_links,
    get_attachments, get_attachment_dir, resolve_attachment_path, to_stored_path,
    get_connection, delete_task, init_db
)
from config import ARCHIVE_DIR, ATTACHMENTS_DIR, APP_VERSION, CHECKPOINTS


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
    Packs: task.json, README.txt and all attachments (active and deleted ones)
    in the attachments/ subfolder of the ZIP.
    Returns path of the created ZIP file.
    """
    _ensure_archive_dir()

    task   = get_task(task_id)
    if not task:
        raise ValueError(f"Task #{task_id} does not exist.")

    checkpoints = get_checkpoints(task_id)
    notes  = get_notes(task_id)
    links  = get_links(task_id)
    attachments = get_attachments(task_id, include_deleted=True)

    # Name of each attachment file inside the ZIP
    for a in attachments:
        folder = "attachments/deleted" if a["deleted"] else "attachments"
        a["arc_name"] = f"{folder}/{os.path.basename(a['stored_path'])}"

    # JSON data
    data = {
        "meta": {
            "export_date":    datetime.now().isoformat(),
            "source":         source,          # 'active' | 'onhold'
            "app_version":    APP_VERSION,
        },
        "task":   dict(task),
        "checkpoints": [dict(c) for c in checkpoints],
        "notes":  [dict(n) for n in notes],
        "links":  [dict(l) for l in links],
        "attachments": [dict(a) for a in attachments],
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

    if attachments:
        readme_lines += ["", "ATTACHMENTS:", "-" * 40]
        for a in attachments:
            tag = "[DEL]" if a["deleted"] else "[ATT]"
            readme_lines.append(f"  {tag} {a['filename']}  (added: {a['added_at'][:10]})")

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

        # Pack attachments
        for a in attachments:
            src_path = resolve_attachment_path(a["stored_path"])
            if not os.path.exists(src_path):
                continue  # file does not exist anymore — skip, do not break
            zf.write(src_path, a["arc_name"])

    # Delete task from database (checkpoints, notes, links and attachments records as well)
    delete_task(task_id)

    # Delete attachments folders of the task from disk — the ZIP has a copy
    att_dirs = {get_attachment_dir(task_id, task["title"])}
    for a in attachments:
        att_dir = os.path.dirname(resolve_attachment_path(a["stored_path"]))
        if os.path.basename(att_dir) == "deleted":
            att_dir = os.path.dirname(att_dir)
        att_dirs.add(att_dir)
    for att_dir in att_dirs:
        # Only folders inside ATTACHMENTS_DIR are removed
        if os.path.dirname(os.path.abspath(att_dir)) != os.path.abspath(ATTACHMENTS_DIR):
            continue
        if os.path.exists(att_dir):
            try:
                shutil.rmtree(att_dir)
            except Exception:
                pass

    return zip_path


# ---------------------------------------------------------------------------
# Import / restore
# ---------------------------------------------------------------------------

def import_task_from_zip(zip_path: str) -> int:
    """
    Restores task from a ZIP file into the database.
    Attachments are restored into a new folder of the task.
    Returns new task id (may differ from the original one).
    """
    init_db()

    with zipfile.ZipFile(zip_path, "r") as zf:
        data  = json.loads(zf.read("task.json").decode("utf-8"))
        names = set(zf.namelist())

        def open_attachment(att: dict):
            arc_name = att.get("arc_name")
            if not arc_name:
                # Archives without arc_name keep attachments under their file names
                folder = "attachments/deleted" if att.get("deleted") else "attachments"
                arc_name = f"{folder}/{att['filename']}"
            return zf.open(arc_name) if arc_name in names else None

        source = data["meta"].get("source", "active")
        return insert_task_data(data, source == "onhold", open_attachment)


def insert_task_data(data: dict, on_hold: bool, open_attachment=None) -> int:
    """
    Inserts a task described by data (format of task.json) as a new task.
    on_hold: restore the task as put on hold
    open_attachment: function(attachment: dict) returning an open file with the
    attachment content, or None if the file is not available.
    Returns id of the new task.
    """
    task   = data["task"]
    # "stages" = key used by archives created before the checkpoint renaming
    checkpoints = data.get("checkpoints", data.get("stages", []))
    notes  = data.get("notes", [])
    links  = data.get("links", [])
    attachments = data.get("attachments", [])

    template_by_name = {c["name"]: c["order"] for c in CHECKPOINTS}

    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO tasks
               (title, description, on_hold, on_hold_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                task["title"],
                task.get("description", ""),
                1 if on_hold else 0,
                task.get("on_hold_at") if on_hold else None,
                task["created_at"],
                datetime.now().isoformat(),
            )
        )
        new_task_id = cur.lastrowid

        # Insert checkpoints (old archives use stage_order / stage_type keys)
        for c in checkpoints:
            if "template_order" in c:
                template_order = c["template_order"]
            else:
                # Archives created before template_order — match with the template by name
                template_order = template_by_name.get(c["name"])
            conn.execute(
                """INSERT INTO task_checkpoints
                   (task_id, checkpoint_order, name, checkpoint_type, completed, iteration_count,
                    template_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_task_id,
                    c["checkpoint_order"] if "checkpoint_order" in c else c["stage_order"],
                    c["name"],
                    c.get("checkpoint_type", c.get("stage_type", "check")),
                    c["completed"],
                    c.get("iteration_count", 0),
                    template_order,
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

        # Attachments — copy files into the new folder of the task
        if attachments and open_attachment:
            new_att_dir = get_attachment_dir(new_task_id, task["title"])
            for a in attachments:
                src = open_attachment(a)
                if src is None:
                    continue  # file was not available when the task was saved
                is_deleted = bool(a.get("deleted", 0))
                dest_dir   = os.path.join(new_att_dir, "deleted") if is_deleted else new_att_dir
                os.makedirs(dest_dir, exist_ok=True)
                file_name  = os.path.basename(
                    a.get("arc_name") or a.get("stored_path") or a["filename"])
                dest_path  = os.path.join(dest_dir, file_name)

                # If the name is already taken — add a time suffix
                if os.path.exists(dest_path):
                    base, ext = os.path.splitext(file_name)
                    dest_path = os.path.join(
                        dest_dir, f"{base}_{datetime.now().strftime('%H%M%S%f')}{ext}")

                with src, open(dest_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)

                conn.execute(
                    """INSERT INTO task_attachments
                       (task_id, filename, stored_path, deleted, added_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        new_task_id,
                        a["filename"],
                        to_stored_path(dest_path),
                        1 if is_deleted else 0,
                        a["added_at"],
                    )
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
