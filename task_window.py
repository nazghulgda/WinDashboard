# task_window.py — single task window

import tkinter as tk
from tkinter import messagebox, filedialog
import os
import re
import shutil
from datetime import datetime

from database import (
    get_task, get_checkpoints, set_checkpoint_completed, set_iteration_count,
    get_task_checkpoint_status,
    get_notes, create_note, update_note,
    get_links, create_link, update_link, delete_link,
    update_task,
    add_checkpoint, delete_checkpoint, update_checkpoint, move_checkpoint,
    get_attachments, create_attachment, soft_delete_attachment,
    get_attachment_dir, resolve_attachment_path,
)
from theme import get_colors

# ---------------------------------------------------------------------------
# Palette — from the active theme (theme.py)
# ---------------------------------------------------------------------------

COLORS = get_colors()

FONT_TITLE   = ("Segoe UI", 16, "bold")
FONT_HEADING = ("Segoe UI", 11, "bold")
FONT_BODY    = ("Segoe UI", 10)
FONT_SMALL   = ("Segoe UI", 8)

HIGHLIGHT_COLORS = [
    ("#FFD700", "Yellow"),
    ("#FF6B6B", "Red"),
    ("#90EE90", "Green"),
    ("#87CEEB", "Blue"),
    ("#DDA0DD", "Purple"),
    ("#FFA500", "Orange"),
]

# ---------------------------------------------------------------------------
# Main task window
# ---------------------------------------------------------------------------

class TaskWindow:
    def __init__(self, parent, task_id: int, on_close=None):
        self.task_id  = task_id
        self.on_close = on_close
        self.task     = get_task(task_id)
        if not self.task:
            messagebox.showerror("Error", f"Task #{task_id} does not exist.")
            return

        self.window = tk.Toplevel(parent)
        self.window.title(self.task["title"])
        self.window.configure(bg=COLORS["bg"])
        self.window.geometry("1100x700")
        self.window.minsize(800, 500)

        self.window.protocol("WM_DELETE_WINDOW", self.close)

        self._open_note_windows = {}
        self._checkpoints_canvas = None  # reference to kanban canvas
        self._build_ui()
        self._load_all()

    # -----------------------------------------------------------------------
    # Building layout
    # -----------------------------------------------------------------------

    def _build_ui(self):
        # Header
        header = tk.Frame(self.window, bg=COLORS["panel"])
        header.pack(fill="x")

        self.title_label = tk.Label(
            header, text=self.task["title"],
            font=FONT_TITLE, bg=COLORS["panel"],
            fg=COLORS["accent"], padx=20, pady=12
        )
        self.title_label.pack(side="left")

        self.desc_label = tk.Label(
            header,
            text=self.task.get("description") or "",
            font=FONT_BODY, bg=COLORS["panel"],
            fg=COLORS["text_dim"], padx=4, pady=12
        )
        if self.task.get("description"):
            self.desc_label.pack(side="left")

        edit_btn = tk.Label(
            header, text="✏", font=FONT_BODY,
            bg=COLORS["panel"], fg=COLORS["text_dim"],
            padx=10, pady=12, cursor="hand2"
        )
        edit_btn.pack(side="left", padx=(4, 0))
        edit_btn.bind("<Button-1>", lambda e: self._edit_task_info())
        edit_btn.bind("<Enter>", lambda e: edit_btn.config(fg=COLORS["accent"]))
        edit_btn.bind("<Leave>", lambda e: edit_btn.config(fg=COLORS["text_dim"]))

        tk.Frame(self.window, bg=COLORS["accent"], height=2).pack(fill="x")

        main = tk.Frame(self.window, bg=COLORS["bg"])
        main.pack(fill="both", expand=True)
        main.rowconfigure(0, weight=1)
        main.rowconfigure(1, weight=0)
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)

        self.kanban_frame = tk.Frame(main, bg=COLORS["bg"])
        self.kanban_frame.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        self._build_kanban_panel(self.kanban_frame)

        self.notes_frame = tk.Frame(main, bg=COLORS["bg"])
        self.notes_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)
        self._build_notes_panel(self.notes_frame)

        bottom = tk.Frame(main, bg=COLORS["bg"])
        bottom.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))
        bottom.columnconfigure(0, weight=3)
        bottom.columnconfigure(1, weight=2)

        self.links_frame = tk.Frame(bottom, bg=COLORS["bg"])
        self.links_frame.grid(row=0, column=0, sticky="new", padx=(0, 6))
        self._build_links_panel(self.links_frame)

        self.attachments_frame = tk.Frame(bottom, bg=COLORS["bg"])
        self.attachments_frame.grid(row=0, column=1, sticky="new", padx=(6, 0))
        self._build_attachments_panel(self.attachments_frame)

    # -----------------------------------------------------------------------
    # Panel: Kanban
    # -----------------------------------------------------------------------

    def _build_kanban_panel(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        hdr = tk.Frame(parent, bg=COLORS["panel"])
        hdr.grid(row=0, column=0, sticky="ew")
        tk.Label(hdr, text="CHECKPOINTS", font=FONT_HEADING,
                 bg=COLORS["panel"], fg=COLORS["accent"],
                 padx=12, pady=8).pack(side="left")
        self.progress_label = tk.Label(
            hdr, text="", font=FONT_SMALL,
            bg=COLORS["panel"], fg=COLORS["text_dim"], padx=12
        )
        self.progress_label.pack(side="right")

        container = tk.Frame(parent, bg=COLORS["bg"])
        container.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        canvas = tk.Canvas(container, bg=COLORS["bg"], highlightthickness=0, bd=0)
        sb = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")
        canvas.grid(row=0, column=0, sticky="nsew")

        self._checkpoints_canvas = canvas  # reference saved

        self.checkpoints_inner = tk.Frame(canvas, bg=COLORS["bg"])
        win_id = canvas.create_window((0, 0), window=self.checkpoints_inner, anchor="nw")

        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))
        self.checkpoints_inner.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

    def _load_kanban(self):
        for w in self.checkpoints_inner.winfo_children():
            w.destroy()

        checkpoints = get_checkpoints(self.task_id)
        checkpoints_count = len(checkpoints)
        status = get_task_checkpoint_status(self.task_id)
        self.progress_label.config(text=status)

        self._checkpoint_vars = {}

        if not checkpoints:
            tk.Label(
                self.checkpoints_inner,
                text="Kanban is empty.\nAdd first checkpoint below.",
                font=FONT_SMALL, bg=COLORS["bg"], fg=COLORS["text_dim"],
                pady=16, justify="center"
            ).pack()
        else:
            for checkpoint in checkpoints:
                is_done = bool(checkpoint["completed"])
                bg = COLORS["checkpoint_done"] if is_done else COLORS["checkpoint_undone"]
                row = tk.Frame(self.checkpoints_inner, bg=bg, pady=6, padx=10)
                row.pack(fill="x", pady=2)

                if checkpoint.get("checkpoint_type", "check") == "counter":
                    self._make_counter_row(row, checkpoint, checkpoints_count)
                else:
                    self._make_check_row(row, checkpoint, checkpoints_count)

        # Checkpoint addition button
        add_frame = tk.Frame(self.checkpoints_inner, bg=COLORS["bg"], pady=4)
        add_frame.pack(fill="x", pady=(6, 0))
        add_btn = tk.Label(
            add_frame, text="+ Add Checkpoint", font=FONT_SMALL,
            bg=COLORS["btn_secondary"], fg=COLORS["text_dim"],
            padx=12, pady=5, cursor="hand2"
        )
        add_btn.pack(side="left", padx=10)
        add_btn.bind("<Button-1>", lambda e: self._add_checkpoint())
        add_btn.bind("<Enter>",
            lambda e: add_btn.config(bg=COLORS["card_hover"], fg=COLORS["text"]))
        add_btn.bind("<Leave>",
            lambda e: add_btn.config(bg=COLORS["btn_secondary"], fg=COLORS["text_dim"]))

    def _make_check_row(self, row: tk.Frame, checkpoint: dict, checkpoints_count: int):
        is_done = bool(checkpoint["completed"])
        bg = COLORS["checkpoint_done"] if is_done else COLORS["checkpoint_undone"]

        var = tk.BooleanVar(value=is_done)
        self._checkpoint_vars[checkpoint["id"]] = var

        cb = tk.Checkbutton(
            row, variable=var,
            bg=bg, activebackground=COLORS["card_hover"],
            selectcolor=COLORS["check_on"], fg=COLORS["text"],
            command=lambda sid=checkpoint["id"], v=var: self._toggle_checkpoint(sid, v)
        )
        cb.pack(side="left")

        tk.Label(
            row, text=checkpoint["name"], font=FONT_BODY, bg=bg,
            fg=COLORS["text"] if is_done else COLORS["text_dim"]
        ).pack(side="left", padx=(4, 0))

        self._pack_checkpoint_controls(row, checkpoint, checkpoints_count, bg)

    def _make_counter_row(self, row: tk.Frame, checkpoint: dict, checkpoints_count: int):
        count = checkpoint.get("iteration_count", 0)
        is_done = count > 0
        bg = COLORS["checkpoint_done"] if is_done else COLORS["checkpoint_undone"]

        minus = tk.Label(
            row, text=" − ", font=FONT_BODY,
            bg=COLORS["btn_secondary"], fg=COLORS["text"],
            cursor="hand2", relief="flat", padx=4
        )
        minus.pack(side="left")

        count_lbl = tk.Label(
            row, text=f"× {count}", font=("Consolas", 10, "bold"),
            bg=bg, fg=COLORS["accent2"] if is_done else COLORS["text_dim"],
            width=5, anchor="center"
        )
        count_lbl.pack(side="left", padx=2)

        plus = tk.Label(
            row, text=" + ", font=FONT_BODY,
            bg=COLORS["btn"], fg="white",
            cursor="hand2", relief="flat", padx=4
        )
        plus.pack(side="left")

        tk.Label(
            row, text=f"  {checkpoint['name']}  (optional, repeatable)",
            font=FONT_BODY, bg=bg,
            fg=COLORS["text"] if is_done else COLORS["text_dim"]
        ).pack(side="left", padx=(6, 0))

        self._pack_checkpoint_controls(row, checkpoint, checkpoints_count, bg)

        def change(delta, sid=checkpoint["id"]):
            current_checkpoints = get_checkpoints(self.task_id)
            current = next((s["iteration_count"] for s in current_checkpoints if s["id"] == sid), 0)
            new_count = max(0, current + delta)
            set_iteration_count(sid, new_count)
            self._reload_kanban_keep_scroll()

        minus.bind("<Button-1>", lambda e: change(-1))
        plus.bind("<Button-1>",  lambda e: change(+1))
        minus.bind("<Enter>", lambda e: minus.config(bg=COLORS["card_hover"]))
        minus.bind("<Leave>", lambda e: minus.config(bg=COLORS["btn_secondary"]))
        plus.bind("<Enter>",  lambda e: plus.config(bg=COLORS["btn_hover"]))
        plus.bind("<Leave>",  lambda e: plus.config(bg=COLORS["btn"]))

    def _pack_checkpoint_controls(self, row: tk.Frame, checkpoint: dict, checkpoints_count: int, bg: str):
        """Adds control buttons (up/down/edit) to the right side of the checkpoint row."""
        order = checkpoint["checkpoint_order"]

        ctrl = tk.Frame(row, bg=bg)
        ctrl.pack(side="right")

        # Edit button
        edit_btn = tk.Label(
            ctrl, text="✏", font=FONT_SMALL, bg=bg,
            fg=COLORS["text_dim"], padx=6, cursor="hand2"
        )
        edit_btn.pack(side="right")
        edit_btn.bind("<Button-1>", lambda e, s=dict(checkpoint): self._edit_checkpoint(s))
        edit_btn.bind("<Enter>", lambda e: edit_btn.config(fg=COLORS["accent"]))
        edit_btn.bind("<Leave>", lambda e: edit_btn.config(fg=COLORS["text_dim"]))

        # Down button
        can_down = order < checkpoints_count
        down_btn = tk.Label(
            ctrl, text="▼", font=("Segoe UI", 7), bg=bg,
            fg=COLORS["text_dim"] if can_down else bg,
            padx=2, cursor="hand2" if can_down else ""
        )
        down_btn.pack(side="right")
        if can_down:
            down_btn.bind("<Button-1>",
                lambda e, sid=checkpoint["id"]: self._move_checkpoint(sid, "down"))
            down_btn.bind("<Enter>", lambda e: down_btn.config(fg=COLORS["text"]))
            down_btn.bind("<Leave>", lambda e: down_btn.config(fg=COLORS["text_dim"]))

        # Up button
        can_up = order > 1
        up_btn = tk.Label(
            ctrl, text="▲", font=("Segoe UI", 7), bg=bg,
            fg=COLORS["text_dim"] if can_up else bg,
            padx=2, cursor="hand2" if can_up else ""
        )
        up_btn.pack(side="right")
        if can_up:
            up_btn.bind("<Button-1>",
                lambda e, sid=checkpoint["id"]: self._move_checkpoint(sid, "up"))
            up_btn.bind("<Enter>", lambda e: up_btn.config(fg=COLORS["text"]))
            up_btn.bind("<Leave>", lambda e: up_btn.config(fg=COLORS["text_dim"]))

    # -----------------------------------------------------------------------
    # Kanban actions
    # -----------------------------------------------------------------------

    def _reload_kanban_keep_scroll(self):
        """Reloads the kanban board while keeping the scroll position."""
        yview = self._checkpoints_canvas.yview() if self._checkpoints_canvas else (0.0, 1.0)
        self._load_kanban()
        if self._checkpoints_canvas and yview[0] > 0:
            self._checkpoints_canvas.after(10,
                lambda y=yview[0]: self._checkpoints_canvas.yview_moveto(y))

    def _toggle_checkpoint(self, checkpoint_id: int, var: tk.BooleanVar):
        set_checkpoint_completed(checkpoint_id, var.get())
        self._reload_kanban_keep_scroll()

    def _move_checkpoint(self, checkpoint_id: int, direction: str):
        yview = self._checkpoints_canvas.yview() if self._checkpoints_canvas else (0.0, 1.0)
        move_checkpoint(self.task_id, checkpoint_id, direction)
        self._load_kanban()
        if self._checkpoints_canvas and yview[0] > 0:
            self._checkpoints_canvas.after(10,
                lambda y=yview[0]: self._checkpoints_canvas.yview_moveto(y))

    def _edit_checkpoint(self, checkpoint: dict):
        dialog = CheckpointEditDialog(self.window, checkpoint)
        self.window.wait_window(dialog.window)
        if dialog.result == "deleted":
            if not delete_checkpoint(checkpoint["id"]):
                messagebox.showinfo(
                    "Delete Checkpoint",
                    "The last checkpoint of a task can not be deleted.\n\n"
                    "A task needs at least one checkpoint to be finished.",
                    parent=self.window
                )
            self._load_kanban()
        elif dialog.result:
            update_checkpoint(checkpoint["id"], dialog.result["name"], dialog.result["checkpoint_type"])
            self._reload_kanban_keep_scroll()

    def _add_checkpoint(self):
        dialog = AddCheckpointDialog(self.window)
        self.window.wait_window(dialog.window)
        if dialog.result:
            add_checkpoint(self.task_id, dialog.result["name"], dialog.result["checkpoint_type"])
            self._load_kanban()
            # Scroll down to show the new checkpoint
            if self._checkpoints_canvas:
                self._checkpoints_canvas.after(50,
                    lambda: self._checkpoints_canvas.yview_moveto(1.0))

    # -----------------------------------------------------------------------
    # Panel: Notes
    # -----------------------------------------------------------------------

    def _build_notes_panel(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        hdr = tk.Frame(parent, bg=COLORS["panel"])
        hdr.grid(row=0, column=0, sticky="ew")
        tk.Label(hdr, text="NOTES", font=FONT_HEADING,
                 bg=COLORS["panel"], fg=COLORS["accent"],
                 padx=12, pady=8).pack(side="left")

        add_btn = tk.Label(
            hdr, text="+ New", font=FONT_SMALL,
            bg=COLORS["btn"], fg="white",
            padx=8, pady=4, cursor="hand2"
        )
        add_btn.pack(side="right", padx=8, pady=6)
        add_btn.bind("<Button-1>", lambda e: self._new_note())
        add_btn.bind("<Enter>", lambda e: add_btn.config(bg=COLORS["btn_hover"]))
        add_btn.bind("<Leave>", lambda e: add_btn.config(bg=COLORS["btn"]))

        container = tk.Frame(parent, bg=COLORS["bg"])
        container.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        canvas = tk.Canvas(container, bg=COLORS["bg"], highlightthickness=0, bd=0)
        sb = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")
        canvas.grid(row=0, column=0, sticky="nsew")

        self.notes_inner = tk.Frame(canvas, bg=COLORS["bg"])
        win_id = canvas.create_window((0, 0), window=self.notes_inner, anchor="nw")

        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))
        self.notes_inner.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

    def _load_notes(self):
        for w in self.notes_inner.winfo_children():
            w.destroy()

        notes = get_notes(self.task_id)

        if not notes:
            tk.Label(
                self.notes_inner, text="No existing notes.",
                font=FONT_SMALL, bg=COLORS["bg"], fg=COLORS["text_dim"],
                pady=12
            ).pack()
            return

        for note in notes:
            self._make_note_row(note)

    def _make_note_row(self, note: dict):
        row = tk.Frame(self.notes_inner, bg=COLORS["card"], pady=6, padx=10, cursor="hand2")
        row.pack(fill="x", pady=2)

        # Line 1: title (left) + edit icon + date (right)
        header_row = tk.Frame(row, bg=COLORS["card"])
        header_row.pack(fill="x")

        title_lbl = tk.Label(header_row, text=note["title"], font=FONT_BODY,
                             bg=COLORS["card"], fg=COLORS["text"], anchor="w")
        title_lbl.pack(side="left", fill="x", expand=True)

        edit_title_btn = tk.Label(header_row, text="✏", font=FONT_SMALL,
                                  bg=COLORS["card"], fg=COLORS["text_dim"],
                                  padx=6, cursor="hand2")
        edit_title_btn.pack(side="right")
        edit_title_btn.bind("<Button-1>",
            lambda e, n=note, lbl=title_lbl: self._edit_note_title(n, lbl))
        edit_title_btn.bind("<Enter>", lambda e: edit_title_btn.config(fg=COLORS["accent"]))
        edit_title_btn.bind("<Leave>", lambda e: edit_title_btn.config(fg=COLORS["text_dim"]))

        # Data: updated if different from created, otherwise created
        if note.get("updated_at") and note["updated_at"] != note["created_at"]:
            dt_str = "updated: " + note["updated_at"][:16].replace("T", " ")
        else:
            dt_str = note["created_at"][:16].replace("T", " ")
        tk.Label(header_row, text=dt_str, font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"]).pack(side="right", padx=(0, 4))

        # Lines 2-3: note content preview
        preview = _note_preview(note.get("content") or "")
        if preview:
            tk.Label(row, text=preview, font=FONT_SMALL,
                     bg=COLORS["card"], fg=COLORS["text_dim"],
                     anchor="w", justify="left").pack(fill="x", pady=(2, 0))

        def open_note(e, n=note):
            nid = n["id"]
            if nid in self._open_note_windows:
                try:
                    w = self._open_note_windows[nid]
                    if w.window.winfo_exists():
                        w.window.lift()
                        return
                except Exception:
                    pass
            def on_note_close(note_id=nid):
                self._open_note_windows.pop(note_id, None)
                self._load_notes()
            editor = NoteEditorWindow(self.window, n,
                on_save=self._load_notes,
                on_close=on_note_close)
            self._open_note_windows[nid] = editor

        row.bind("<Button-1>", open_note)
        for child in row.winfo_children():
            if child is not edit_title_btn and child is not header_row:
                child.bind("<Button-1>", open_note)
        title_lbl.bind("<Button-1>", open_note)

        def on_enter(e, r=row): _set_bg(r, COLORS["card_hover"])
        def on_leave(e, r=row): _set_bg(r, COLORS["card"])
        row.bind("<Enter>", on_enter)
        row.bind("<Leave>", on_leave)

    def _new_note(self):
        dialog = NewNoteDialog(self.window)
        self.window.wait_window(dialog.window)
        if dialog.result:
            create_note(self.task_id, dialog.result["title"])
            self._load_notes()

    def _edit_note_title(self, note: dict, title_lbl: tk.Label):
        dialog = EditNoteTitleDialog(self.window, note["title"])
        self.window.wait_window(dialog.window)
        if dialog.result:
            new_title = dialog.result
            update_note(note["id"], new_title, note.get("content") or "")
            note["title"] = new_title
            title_lbl.config(text=new_title)
            # Note opened in the editor shows the new title as well
            editor = self._open_note_windows.get(note["id"])
            if editor is not None and _editor_alive(editor):
                editor.set_title(new_title)

    # -----------------------------------------------------------------------
    # Panel: Links
    # -----------------------------------------------------------------------

    def _build_links_panel(self, parent):
        parent.columnconfigure(0, weight=1)

        tk.Frame(parent, bg=COLORS["border"], height=1).pack(fill="x", pady=(0, 6))

        hdr = tk.Frame(parent, bg=COLORS["panel"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="LINKS", font=FONT_HEADING,
                 bg=COLORS["panel"], fg=COLORS["accent"],
                 padx=12, pady=6).pack(side="left")

        for label, ltype in [("+ File", "file"), ("+ Folder", "folder")]:
            btn = tk.Label(
                hdr, text=label, font=FONT_SMALL,
                bg=COLORS["btn"], fg="white",
                padx=8, pady=4, cursor="hand2"
            )
            btn.pack(side="right", padx=(4, 8), pady=4)
            btn.bind("<Button-1>", lambda e, t=ltype: self._add_link(t))
            btn.bind("<Enter>", lambda e, b=btn: b.config(bg=COLORS["btn_hover"]))
            btn.bind("<Leave>", lambda e, b=btn: b.config(bg=COLORS["btn"]))

        self.links_container = tk.Frame(parent, bg=COLORS["bg"])
        self.links_container.pack(fill="x", pady=(4, 0))

    def _load_links(self):
        for w in self.links_container.winfo_children():
            w.destroy()

        links = get_links(self.task_id)

        if not links:
            tk.Label(
                self.links_container, text="No links available. Add a file or folder.",
                font=FONT_SMALL, bg=COLORS["bg"], fg=COLORS["text_dim"],
                pady=6
            ).pack(side="left")
            return

        for link in links:
            self._make_link_chip(link)

    def _make_link_chip(self, link: dict):
        icon = "📁" if link["link_type"] == "folder" else "📄"

        chip = tk.Frame(
            self.links_container, bg=COLORS["card"],
            padx=8, pady=4, cursor="hand2"
        )
        chip.pack(side="left", padx=4, pady=4)

        label_lbl = tk.Label(
            chip, text=f"{icon} {link['label']}",
            font=FONT_SMALL, bg=COLORS["card"], fg=COLORS["text"]
        )
        label_lbl.pack(side="left")

        edit_btn = tk.Label(
            chip, text="✏", font=FONT_SMALL,
            bg=COLORS["card"], fg=COLORS["text_dim"],
            cursor="hand2", padx=3
        )
        edit_btn.pack(side="left")
        edit_btn.bind("<Button-1>", lambda e, l=dict(link): self._edit_link(l))
        edit_btn.bind("<Enter>", lambda e: edit_btn.config(fg=COLORS["accent"]))
        edit_btn.bind("<Leave>", lambda e: edit_btn.config(fg=COLORS["text_dim"]))

        del_btn = tk.Label(
            chip, text="×", font=FONT_BODY,
            bg=COLORS["card"], fg=COLORS["text_dim"],
            cursor="hand2", padx=3
        )
        del_btn.pack(side="left")
        del_btn.bind("<Button-1>", lambda e, l=dict(link): self._delete_link(l))
        del_btn.bind("<Enter>", lambda e: del_btn.config(fg=COLORS["accent"]))
        del_btn.bind("<Leave>", lambda e: del_btn.config(fg=COLORS["text_dim"]))

        _make_tooltip(chip, link["path"])
        for child in chip.winfo_children():
            _make_tooltip(child, link["path"])

        # Click on chip (outside buttons) opens the path
        non_btn = [label_lbl, chip]
        for w in non_btn:
            w.bind("<Button-1>", lambda e, p=link["path"], t=link["link_type"]: _open_path(p, t))

        def on_enter(e, c=chip): _set_bg(c, COLORS["card_hover"])
        def on_leave(e, c=chip): _set_bg(c, COLORS["card"])
        chip.bind("<Enter>", on_enter)
        chip.bind("<Leave>", on_leave)

    def _edit_link(self, link: dict):
        dialog = LinkEditDialog(self.window, link)
        self.window.wait_window(dialog.window)
        if dialog.result:
            update_link(link["id"], dialog.result["label"],
                        dialog.result["path"], link["link_type"])
            self._load_links()

    def _add_link(self, link_type: str):
        if link_type == "folder":
            path = filedialog.askdirectory(title="Select Folder", parent=self.window)
        else:
            path = filedialog.askopenfilename(title="Select File", parent=self.window)

        if not path:
            return

        path = os.path.normpath(path)
        label = os.path.basename(path) or path

        create_link(self.task_id, label, path, link_type)
        self._load_links()

    def _delete_link(self, link: dict):
        if not messagebox.askyesno(
            "Delete Link",
            f"Delete link?\n\n{link['label']}\n{link['path']}",
            parent=self.window
        ):
            return
        delete_link(link["id"])
        self._load_links()

    # -----------------------------------------------------------------------
    # Panel: Attachments
    # -----------------------------------------------------------------------

    def _build_attachments_panel(self, parent):
        parent.columnconfigure(0, weight=1)

        tk.Frame(parent, bg=COLORS["border"], height=1).pack(fill="x", pady=(0, 6))

        hdr = tk.Frame(parent, bg=COLORS["panel"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="ATTACHMENTS", font=FONT_HEADING,
                 bg=COLORS["panel"], fg=COLORS["accent"],
                 padx=12, pady=6).pack(side="left")

        add_btn = tk.Label(
            hdr, text="+ Add file", font=FONT_SMALL,
            bg=COLORS["btn"], fg="white",
            padx=8, pady=4, cursor="hand2"
        )
        add_btn.pack(side="right", padx=(4, 8), pady=4)
        add_btn.bind("<Button-1>", lambda e: self._add_attachment())
        add_btn.bind("<Enter>", lambda e: add_btn.config(bg=COLORS["btn_hover"]))
        add_btn.bind("<Leave>", lambda e: add_btn.config(bg=COLORS["btn"]))

        self.attachments_container = tk.Frame(parent, bg=COLORS["bg"])
        self.attachments_container.pack(fill="x", pady=(4, 0))

    def _load_attachments(self):
        for w in self.attachments_container.winfo_children():
            w.destroy()

        attachments = get_attachments(self.task_id)

        if not attachments:
            tk.Label(
                self.attachments_container, text="No attachments.",
                font=FONT_SMALL, bg=COLORS["bg"], fg=COLORS["text_dim"],
                pady=6
            ).pack(side="left")
            return

        for att in attachments:
            self._make_attachment_chip(att)

    def _make_attachment_chip(self, att: dict):
        path = resolve_attachment_path(att["stored_path"])

        chip = tk.Frame(
            self.attachments_container, bg=COLORS["card"],
            padx=8, pady=4, cursor="hand2"
        )
        chip.pack(side="left", padx=4, pady=4)

        label_lbl = tk.Label(
            chip, text=f"📎 {att['filename']}",
            font=FONT_SMALL, bg=COLORS["card"], fg=COLORS["text"]
        )
        label_lbl.pack(side="left")

        del_btn = tk.Label(
            chip, text="×", font=FONT_BODY,
            bg=COLORS["card"], fg=COLORS["text_dim"],
            cursor="hand2", padx=3
        )
        del_btn.pack(side="left")
        del_btn.bind("<Button-1>", lambda e, a=dict(att): self._delete_attachment(a))
        del_btn.bind("<Enter>", lambda e: del_btn.config(fg=COLORS["accent"]))
        del_btn.bind("<Leave>", lambda e: del_btn.config(fg=COLORS["text_dim"]))

        _make_tooltip(chip, path)
        _make_tooltip(label_lbl, path)

        # Click on chip (outside buttons) opens the file
        for w in [label_lbl, chip]:
            w.bind("<Button-1>", lambda e, p=path: _open_path(p, "file"))

        def on_enter(e, c=chip): _set_bg(c, COLORS["card_hover"])
        def on_leave(e, c=chip): _set_bg(c, COLORS["card"])
        chip.bind("<Enter>", on_enter)
        chip.bind("<Leave>", on_leave)

    def _attachments_dir(self) -> str:
        """Returns attachments folder of this task. A folder which the task already
        uses is kept, also when the task title was changed in the meantime."""
        for att in get_attachments(self.task_id, include_deleted=True):
            folder = os.path.dirname(resolve_attachment_path(att["stored_path"]))
            if os.path.basename(folder) == "deleted":
                folder = os.path.dirname(folder)
            return folder
        return get_attachment_dir(self.task_id, self.task["title"])

    def _add_attachment(self):
        paths = filedialog.askopenfilenames(title="Select Files to Attach", parent=self.window)
        if not paths:
            return

        task_dir = self._attachments_dir()
        os.makedirs(task_dir, exist_ok=True)

        for src_path in paths:
            filename  = os.path.basename(src_path)
            dest_path = os.path.join(task_dir, filename)

            # If a file with the same name already exists — add a time suffix
            if os.path.exists(dest_path):
                base, ext = os.path.splitext(filename)
                filename  = f"{base}_{datetime.now().strftime('%H%M%S')}{ext}"
                dest_path = os.path.join(task_dir, filename)

            try:
                shutil.copy2(src_path, dest_path)
                create_attachment(self.task_id, filename, dest_path)
            except Exception as ex:
                messagebox.showerror(
                    "Error",
                    f"Failed to attach the file:\n{src_path}\n\n{ex}",
                    parent=self.window
                )

        self._load_attachments()

    def _delete_attachment(self, att: dict):
        if not messagebox.askyesno(
            "Delete Attachment",
            f"Delete attachment?\n\n{att['filename']}\n\n"
            "The file will be moved to the 'deleted' folder — "
            "you can manually recover it from there.",
            parent=self.window
        ):
            return

        src = resolve_attachment_path(att["stored_path"])
        deleted_dir = os.path.join(os.path.dirname(src), "deleted")
        dest = os.path.join(deleted_dir, os.path.basename(src))

        try:
            os.makedirs(deleted_dir, exist_ok=True)
            if os.path.exists(dest):
                base, ext = os.path.splitext(os.path.basename(src))
                dest = os.path.join(
                    deleted_dir, f"{base}_{datetime.now().strftime('%H%M%S')}{ext}")
            if os.path.exists(src):
                os.rename(src, dest)
            soft_delete_attachment(att["id"], dest)
        except Exception as ex:
            messagebox.showerror(
                "Error",
                f"Failed to delete attachment:\n{ex}",
                parent=self.window
            )
            return

        self._load_attachments()

    # -----------------------------------------------------------------------
    # Loading Everything / closing
    # -----------------------------------------------------------------------

    def _load_all(self):
        self._load_kanban()
        self._load_notes()
        self._load_links()
        self._load_attachments()

    def _note_editors(self) -> list:
        """Returns note editor windows which are open now."""
        self._open_note_windows = {nid: ed for nid, ed in self._open_note_windows.items()
                                   if _editor_alive(ed)}
        return list(self._open_note_windows.values())

    def rebuild(self):
        """Builds content of the window again with colors of the active theme.
        The window and note editors opened from it stay open."""
        for w in self.window.winfo_children():
            if not isinstance(w, tk.Toplevel):
                w.destroy()
        self.window.configure(bg=COLORS["bg"])
        self._build_ui()
        self._load_all()
        for editor in self._note_editors():
            editor.rebuild()

    def reload(self):
        """Reads the task again after the database content was replaced.
        The window is closed if the task does not exist anymore."""
        self.task = get_task(self.task_id)
        if not self.task:
            self.window.destroy()
            return
        existing = {n["id"] for n in get_notes(self.task_id)}
        for editor in self._note_editors():
            if editor.note["id"] not in existing:
                editor.window.destroy()
        self.rebuild()

    def save_open_notes(self):
        """Saves unsaved changes of all notes opened from this window."""
        for editor in self._note_editors():
            editor.save_if_changed()

    def close(self):
        """Closes the window. Notes are never lost — unsaved changes are saved first."""
        self.save_open_notes()
        if self.on_close:
            self.on_close()
        self.window.destroy()

    def _edit_task_info(self):
        dialog = EditTaskDialog(self.window, self.task["title"],
                                self.task.get("description") or "")
        self.window.wait_window(dialog.window)
        if dialog.result:
            new_title = dialog.result["title"]
            new_desc  = dialog.result["description"]
            update_task(self.task_id, new_title, new_desc)
            self.task["title"]       = new_title
            self.task["description"] = new_desc
            self.window.title(new_title)
            self.title_label.config(text=new_title)
            self.desc_label.config(text=new_desc)
            if new_desc:
                self.desc_label.pack(side="left", padx=(4,0))
            else:
                self.desc_label.pack_forget()


# ---------------------------------------------------------------------------
# CheckpointEditDialog: Edit Checkpoint (change name, type, delete)
# ---------------------------------------------------------------------------

class CheckpointEditDialog:
    def __init__(self, parent, checkpoint: dict):
        self.checkpoint  = checkpoint
        self.result = None  # None=cancelled, "deleted"=deleted, dict=saved

        self.window = tk.Toplevel(parent)
        self.window.title("Edit Checkpoint")
        self.window.configure(bg=COLORS["bg"])
        self.window.geometry("420x250")
        self.window.resizable(False, False)
        self.window.grab_set()

        tk.Label(self.window, text="Edit Checkpoint", font=FONT_HEADING,
                 bg=COLORS["bg"], fg=COLORS["accent"],
                 pady=12, padx=20).pack(anchor="w")
        tk.Frame(self.window, bg=COLORS["accent"], height=1).pack(fill="x")

        form = tk.Frame(self.window, bg=COLORS["bg"], padx=20, pady=14)
        form.pack(fill="both", expand=True)

        tk.Label(form, text="Checkpoint Name", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w")
        self.name_var = tk.StringVar(value=checkpoint["name"])
        entry = tk.Entry(form, textvariable=self.name_var, font=FONT_BODY,
                         bg=COLORS["card"], fg=COLORS["text"],
                         insertbackground=COLORS["text"], relief="flat")
        entry.pack(fill="x", ipady=5, pady=(2, 12))
        entry.focus_set()
        entry.select_range(0, "end")

        tk.Label(form, text="Checkpoint Type", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w")
        self.type_var = tk.StringVar(value=checkpoint.get("checkpoint_type", "check"))
        type_row = tk.Frame(form, bg=COLORS["bg"])
        type_row.pack(anchor="w", pady=(2, 14))
        radio_style = dict(
            bg=COLORS["bg"], fg=COLORS["text"],
            activebackground=COLORS["bg"], activeforeground=COLORS["text"],
            selectcolor=COLORS["card"], font=FONT_BODY
        )
        tk.Radiobutton(type_row, text="Checkbox",
                       variable=self.type_var, value="check",
                       **radio_style).pack(side="left", padx=(0, 20))
        tk.Radiobutton(type_row, text="Counter (+/−)",
                       variable=self.type_var, value="counter",
                       **radio_style).pack(side="left")

        btn_row = tk.Frame(form, bg=COLORS["bg"])
        btn_row.pack(fill="x")

        # Delete button (left)
        del_btn = tk.Label(btn_row, text="🗑 Delete Checkpoint", font=FONT_BODY,
                           bg="#5a1515", fg="#ff9999",
                           padx=10, pady=6, cursor="hand2")
        del_btn.pack(side="left")
        del_btn.bind("<Button-1>", lambda e: self._delete())
        del_btn.bind("<Enter>", lambda e: del_btn.config(bg="#7a2020"))
        del_btn.bind("<Leave>", lambda e: del_btn.config(bg="#5a1515"))

        # Cancel + Save (right)
        cancel = tk.Label(btn_row, text="Cancel", font=FONT_BODY,
                          bg=COLORS["btn_secondary"], fg=COLORS["text_dim"],
                          padx=10, pady=6, cursor="hand2")
        cancel.pack(side="right", padx=(8, 0))
        cancel.bind("<Button-1>", lambda e: self.window.destroy())

        save = tk.Label(btn_row, text="Save", font=("Segoe UI", 10, "bold"),
                        bg=COLORS["btn"], fg="white",
                        padx=10, pady=6, cursor="hand2")
        save.pack(side="right")
        save.bind("<Button-1>", lambda e: self._save())
        save.bind("<Enter>", lambda e: save.config(bg=COLORS["btn_hover"]))
        save.bind("<Leave>", lambda e: save.config(bg=COLORS["btn"]))

        self.window.bind("<Return>", lambda e: self._save())
        self.window.bind("<Escape>", lambda e: self.window.destroy())

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            return
        self.result = {"name": name, "checkpoint_type": self.type_var.get()}
        self.window.destroy()

    def _delete(self):
        if messagebox.askyesno(
            "Delete Checkpoint",
            f"Are you sure you want to delete the checkpoint:\n\n\"{self.checkpoint['name']}\"?\n\n"
            "Remaining checkpoints will be automatically renumbered.",
            parent=self.window
        ):
            self.result = "deleted"
            self.window.destroy()


# ---------------------------------------------------------------------------
# Dialog: Add Checkpoint
# ---------------------------------------------------------------------------

class AddCheckpointDialog:
    def __init__(self, parent):
        self.result = None

        self.window = tk.Toplevel(parent)
        self.window.title("Add Checkpoint")
        self.window.configure(bg=COLORS["bg"])
        self.window.geometry("420x220")
        self.window.resizable(False, False)
        self.window.grab_set()

        tk.Label(self.window, text="Add Checkpoint", font=FONT_HEADING,
                 bg=COLORS["bg"], fg=COLORS["accent"],
                 pady=12, padx=20).pack(anchor="w")
        tk.Frame(self.window, bg=COLORS["accent"], height=1).pack(fill="x")

        form = tk.Frame(self.window, bg=COLORS["bg"], padx=20, pady=14)
        form.pack(fill="both", expand=True)

        tk.Label(form, text="Checkpoint Name", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w")
        self.name_var = tk.StringVar()
        entry = tk.Entry(form, textvariable=self.name_var, font=FONT_BODY,
                         bg=COLORS["card"], fg=COLORS["text"],
                         insertbackground=COLORS["text"], relief="flat")
        entry.pack(fill="x", ipady=5, pady=(2, 12))
        entry.focus_set()

        tk.Label(form, text="Checkpoint Type", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w")
        self.type_var = tk.StringVar(value="check")
        type_row = tk.Frame(form, bg=COLORS["bg"])
        type_row.pack(anchor="w", pady=(2, 14))
        radio_style = dict(
            bg=COLORS["bg"], fg=COLORS["text"],
            activebackground=COLORS["bg"], activeforeground=COLORS["text"],
            selectcolor=COLORS["card"], font=FONT_BODY
        )
        tk.Radiobutton(type_row, text="Checkbox",
                       variable=self.type_var, value="check",
                       **radio_style).pack(side="left", padx=(0, 20))
        tk.Radiobutton(type_row, text="Counter (+/−)",
                       variable=self.type_var, value="counter",
                       **radio_style).pack(side="left")

        btn_row = tk.Frame(form, bg=COLORS["bg"])
        btn_row.pack(fill="x")

        cancel = tk.Label(btn_row, text="Cancel", font=FONT_BODY,
                          bg=COLORS["btn_secondary"], fg=COLORS["text_dim"],
                          padx=10, pady=6, cursor="hand2")
        cancel.pack(side="right", padx=(8, 0))
        cancel.bind("<Button-1>", lambda e: self.window.destroy())

        add_btn = tk.Label(btn_row, text="Add", font=("Segoe UI", 10, "bold"),
                           bg=COLORS["btn"], fg="white",
                           padx=10, pady=6, cursor="hand2")
        add_btn.pack(side="right")
        add_btn.bind("<Button-1>", lambda e: self._confirm())
        add_btn.bind("<Enter>", lambda e: add_btn.config(bg=COLORS["btn_hover"]))
        add_btn.bind("<Leave>", lambda e: add_btn.config(bg=COLORS["btn"]))

        self.window.bind("<Return>", lambda e: self._confirm())
        self.window.bind("<Escape>", lambda e: self.window.destroy())

    def _confirm(self):
        name = self.name_var.get().strip()
        if not name:
            return
        self.result = {"name": name, "checkpoint_type": self.type_var.get()}
        self.window.destroy()


# ---------------------------------------------------------------------------
# Dialog: New Note (title only)
# ---------------------------------------------------------------------------

class NewNoteDialog:
    def __init__(self, parent):
        self.result = None

        self.window = tk.Toplevel(parent)
        self.window.title("New Note")
        self.window.configure(bg=COLORS["bg"])
        self.window.geometry("400x160")
        self.window.resizable(False, False)
        self.window.grab_set()

        tk.Label(
            self.window, text="Note Title",
            font=FONT_HEADING, bg=COLORS["bg"],
            fg=COLORS["accent"], pady=12, padx=20
        ).pack(anchor="w")

        self.title_var = tk.StringVar()
        entry = tk.Entry(
            self.window, textvariable=self.title_var,
            font=FONT_BODY, bg=COLORS["card"], fg=COLORS["text"],
            insertbackground=COLORS["text"], relief="flat"
        )
        entry.pack(fill="x", padx=20, ipady=6)
        entry.focus_set()

        btn_row = tk.Frame(self.window, bg=COLORS["bg"])
        btn_row.pack(fill="x", padx=20, pady=16)

        confirm = tk.Label(
            btn_row, text="Create",
            font=("Segoe UI", 10, "bold"),
            bg=COLORS["btn"], fg="white",
            padx=14, pady=6, cursor="hand2"
        )
        confirm.pack(side="right")
        confirm.bind("<Button-1>", lambda e: self._confirm())
        confirm.bind("<Enter>", lambda e: confirm.config(bg=COLORS["btn_hover"]))
        confirm.bind("<Leave>", lambda e: confirm.config(bg=COLORS["btn"]))

        self.window.bind("<Return>", lambda e: self._confirm())
        self.window.bind("<Escape>", lambda e: self.window.destroy())

    def _confirm(self):
        title = self.title_var.get().strip()
        if not title:
            return
        self.result = {"title": title}
        self.window.destroy()


# ---------------------------------------------------------------------------
# Dialog: Edit Task Title and Description
# ---------------------------------------------------------------------------

class EditTaskDialog:
    def __init__(self, parent, current_title: str, current_desc: str):
        self.result = None

        self.window = tk.Toplevel(parent)
        self.window.title("Edit Task")
        self.window.configure(bg=COLORS["bg"])
        self.window.geometry("460x300")
        self.window.resizable(False, False)
        self.window.grab_set()

        tk.Label(self.window, text="Edit Task",
                 font=FONT_HEADING, bg=COLORS["bg"],
                 fg=COLORS["accent"], pady=12).pack()
        tk.Frame(self.window, bg=COLORS["accent"], height=1).pack(fill="x")

        form = tk.Frame(self.window, bg=COLORS["bg"], padx=24, pady=16)
        form.pack(fill="both", expand=True)

        tk.Label(form, text="Title *", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w")
        self.title_var = tk.StringVar(value=current_title)
        title_entry = tk.Entry(form, textvariable=self.title_var,
                               font=FONT_BODY, bg=COLORS["card"], fg=COLORS["text"],
                               insertbackground=COLORS["text"], relief="flat")
        title_entry.pack(fill="x", ipady=5, pady=(2, 12))
        title_entry.focus_set()
        title_entry.select_range(0, "end")

        tk.Label(form, text="Description (optional)", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w")
        self.desc_text = tk.Text(form, height=4, font=FONT_BODY,
                                 bg=COLORS["card"], fg=COLORS["text"],
                                 insertbackground=COLORS["text"], relief="flat", wrap="word")
        self.desc_text.insert("1.0", current_desc)
        self.desc_text.pack(fill="x", pady=(2, 16))

        btn_row = tk.Frame(form, bg=COLORS["bg"])
        btn_row.pack(fill="x")

        cancel = tk.Label(btn_row, text="Cancel", font=FONT_BODY,
                          bg=COLORS["btn_secondary"], fg=COLORS["text_dim"],
                          padx=14, pady=6, cursor="hand2")
        cancel.pack(side="right", padx=(8, 0))
        cancel.bind("<Button-1>", lambda e: self.window.destroy())

        confirm = tk.Label(btn_row, text="Save",
                           font=("Segoe UI", 10, "bold"),
                           bg=COLORS["btn"], fg="white",
                           padx=14, pady=6, cursor="hand2")
        confirm.pack(side="right")
        confirm.bind("<Button-1>", lambda e: self._confirm())
        confirm.bind("<Enter>", lambda e: confirm.config(bg=COLORS["btn_hover"]))
        confirm.bind("<Leave>", lambda e: confirm.config(bg=COLORS["btn"]))

        self.window.bind("<Return>", lambda e: self._confirm())
        self.window.bind("<Escape>", lambda e: self.window.destroy())

    def _confirm(self):
        title = self.title_var.get().strip()
        if not title:
            return
        self.result = {
            "title":       title,
            "description": self.desc_text.get("1.0", "end").strip()
        }
        self.window.destroy()


# ---------------------------------------------------------------------------
# Dialog: Edit Note Title
# ---------------------------------------------------------------------------

class EditNoteTitleDialog:
    def __init__(self, parent, current_title: str):
        self.result = None

        self.window = tk.Toplevel(parent)
        self.window.title("Edit Note Title")
        self.window.configure(bg=COLORS["bg"])
        self.window.geometry("400x150")
        self.window.resizable(False, False)
        self.window.grab_set()

        tk.Label(self.window, text="Note Title",
                 font=FONT_HEADING, bg=COLORS["bg"],
                 fg=COLORS["accent"], pady=12, padx=20).pack(anchor="w")

        self.title_var = tk.StringVar(value=current_title)
        entry = tk.Entry(self.window, textvariable=self.title_var,
                         font=FONT_BODY, bg=COLORS["card"], fg=COLORS["text"],
                         insertbackground=COLORS["text"], relief="flat")
        entry.pack(fill="x", padx=20, ipady=6)
        entry.focus_set()
        entry.select_range(0, "end")

        btn_row = tk.Frame(self.window, bg=COLORS["bg"])
        btn_row.pack(fill="x", padx=20, pady=16)

        confirm = tk.Label(btn_row, text="Save",
                           font=("Segoe UI", 10, "bold"),
                           bg=COLORS["btn"], fg="white",
                           padx=14, pady=6, cursor="hand2")
        confirm.pack(side="right")
        confirm.bind("<Button-1>", lambda e: self._confirm())
        confirm.bind("<Enter>", lambda e: confirm.config(bg=COLORS["btn_hover"]))
        confirm.bind("<Leave>", lambda e: confirm.config(bg=COLORS["btn"]))

        self.window.bind("<Return>", lambda e: self._confirm())
        self.window.bind("<Escape>", lambda e: self.window.destroy())

    def _confirm(self):
        title = self.title_var.get().strip()
        if not title:
            return
        self.result = title
        self.window.destroy()


# ---------------------------------------------------------------------------
# Note Editor Window
# ---------------------------------------------------------------------------

class NoteEditorWindow:
    def __init__(self, parent, note: dict, on_save=None, on_close=None):
        self.note     = note
        self.on_save  = on_save
        self.on_close = on_close
        self._edit_mode = False

        self.window = tk.Toplevel(parent)
        self.window.title(note["title"])
        self.window.configure(bg=COLORS["bg"])
        self.window.geometry("700x520")
        self.window.minsize(500, 350)

        if on_close:
            self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._render_preview()

    def _on_close(self):
        if self.has_unsaved_changes():
            answer = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes in the note.\n\nDo you want to save them?",
                parent=self.window
            )
            if answer is None:
                return
            elif answer:
                self._save()
        if self.on_close:
            self.on_close()
        self.window.destroy()

    def has_unsaved_changes(self) -> bool:
        if not self._edit_mode:
            return False
        return self.editor_text.get("1.0", "end-1c") != (self.note.get("content") or "")

    def save_if_changed(self):
        """Saves the note if it has unsaved changes — used when the window is closed
        from outside (task window or application closed)."""
        if self.has_unsaved_changes():
            self._save()

    def set_title(self, title: str):
        """Shows new title of the note in the window."""
        self.note["title"] = title
        self.window.title(title)
        self.title_label.config(text=title)

    def rebuild(self):
        """Builds content of the window again with colors of the active theme.
        Text which is being edited and the cursor position are kept."""
        editing = self._edit_mode
        if editing:
            text   = self.editor_text.get("1.0", "end-1c")
            cursor = self.editor_text.index("insert")

        for w in self.window.winfo_children():
            if not isinstance(w, tk.Toplevel):
                w.destroy()
        self.window.configure(bg=COLORS["bg"])
        self._edit_mode = False
        self._build_ui()
        self._render_preview()

        if editing:
            self._enter_edit_mode()
            self.editor_text.delete("1.0", "end")
            self.editor_text.insert("1.0", text)
            self.editor_text.mark_set("insert", cursor)

    def _build_ui(self):
        hdr = tk.Frame(self.window, bg=COLORS["panel"])
        hdr.pack(fill="x")

        self.title_label = tk.Label(
            hdr, text=self.note["title"],
            font=FONT_HEADING, bg=COLORS["panel"],
            fg=COLORS["accent"], padx=16, pady=10
        )
        self.title_label.pack(side="left")

        dt = self.note["created_at"][:16].replace("T", "  ")
        tk.Label(
            hdr, text=dt,
            font=FONT_SMALL, bg=COLORS["panel"],
            fg=COLORS["text_dim"], padx=8
        ).pack(side="left")

        self.mode_btn = tk.Label(
            hdr, text="✏ Edit",
            font=FONT_SMALL, bg=COLORS["btn"], fg="white",
            padx=10, pady=4, cursor="hand2"
        )
        self.mode_btn.pack(side="right", padx=12, pady=8)
        self.mode_btn.bind("<Button-1>", lambda e: self._toggle_mode())
        self.mode_btn.bind("<Enter>", lambda e: self.mode_btn.config(bg=COLORS["btn_hover"]))
        self.mode_btn.bind("<Leave>", lambda e: self.mode_btn.config(bg=COLORS["btn"]))

        tk.Frame(self.window, bg=COLORS["accent"], height=2).pack(fill="x")

        self.toolbar = tk.Frame(self.window, bg=COLORS["panel"])
        self._build_toolbar()

        self.content_frame = tk.Frame(self.window, bg=COLORS["bg"])
        self.content_frame.pack(fill="both", expand=True, padx=12, pady=8)
        self.content_frame.rowconfigure(0, weight=1)
        self.content_frame.columnconfigure(0, weight=1)

        self.preview_text = tk.Text(
            self.content_frame,
            font=FONT_BODY, bg=COLORS["card"], fg=COLORS["text"],
            relief="flat", wrap="word", padx=12, pady=8,
            state="disabled", cursor="arrow"
        )
        self.preview_text.grid(row=0, column=0, sticky="nsew")
        self._configure_preview_tags()

        self.editor_text = tk.Text(
            self.content_frame,
            font=("Consolas", 10), bg=COLORS["panel"], fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat", wrap="word", padx=12, pady=8
        )
        sb = tk.Scrollbar(self.content_frame, orient="vertical")
        sb.grid(row=0, column=1, sticky="ns")
        self.preview_text.configure(yscrollcommand=sb.set)
        self.editor_text.configure(yscrollcommand=sb.set)

    def _configure_preview_tags(self):
        self.preview_text.tag_configure("bold",          font=("Segoe UI", 10, "bold"))
        self.preview_text.tag_configure("italic",        font=("Segoe UI", 10, "italic"))
        self.preview_text.tag_configure("bold_italic",   font=("Segoe UI", 10, "bold italic"))
        self.preview_text.tag_configure("strikethrough", overstrike=True)
        for color, _ in HIGHLIGHT_COLORS:
            self.preview_text.tag_configure(f"hl_{color}", background=color, foreground="#1a1a2e")

    def _build_toolbar(self):
        tools = [
            ("B",  "bold",          self._fmt_bold),
            ("I",  "italic",        self._fmt_italic),
            ("S",  "strikethrough", self._fmt_strike),
            ("🎨", "highlight",     self._fmt_highlight),
        ]
        fonts = {
            "bold":          ("Segoe UI", 10, "bold"),
            "italic":        ("Segoe UI", 10, "italic"),
            "strikethrough": ("Segoe UI", 10),
        }
        for symbol, ftype, cmd in tools:
            btn = tk.Label(
                self.toolbar, text=symbol,
                font=fonts.get(ftype, FONT_BODY),
                bg=COLORS["panel"], fg=COLORS["text"],
                padx=10, pady=4, cursor="hand2",
                relief="flat"
            )
            btn.pack(side="left", padx=2, pady=4)
            btn.bind("<Button-1>", lambda e, c=cmd: c())
            btn.bind("<Enter>", lambda e, b=btn: b.config(bg=COLORS["card_hover2"]))
            btn.bind("<Leave>", lambda e, b=btn: b.config(bg=COLORS["panel"]))

        tk.Frame(self.toolbar, bg=COLORS["border"], width=1).pack(side="left", fill="y", padx=6)

        tk.Label(
            self.toolbar,
            text="**bold**  *italic*  ~~strikethrough~~",
            font=FONT_SMALL, bg=COLORS["panel"], fg=COLORS["text_dim"],
            padx=8
        ).pack(side="left")

    def _toggle_mode(self):
        if self._edit_mode:
            self._save()
        else:
            self._enter_edit_mode()

    def _enter_edit_mode(self):
        self._edit_mode = True
        self.mode_btn.config(text="💾 Save")

        self.editor_text.delete("1.0", "end")
        self.editor_text.insert("1.0", self.note.get("content") or "")

        self.toolbar.pack(fill="x", before=self.content_frame)
        self.preview_text.grid_remove()
        self.editor_text.grid(row=0, column=0, sticky="nsew")
        self.editor_text.focus_set()

    def _save(self):
        content = self.editor_text.get("1.0", "end-1c")
        update_note(self.note["id"], self.note["title"], content)
        self.note["content"] = content
        self._edit_mode = False
        self.mode_btn.config(text="✏ Edit")

        self.toolbar.pack_forget()
        self.editor_text.grid_remove()
        self.preview_text.grid(row=0, column=0, sticky="nsew")

        self._render_preview()
        if self.on_save:
            self.on_save()

    def _render_preview(self):
        content = self.note.get("content") or ""
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")

        for line in content.split("\n"):
            self._insert_markdown_line(line)
            self.preview_text.insert("end", "\n")

        self.preview_text.configure(state="disabled")

    def _insert_markdown_line(self, line: str):
        self._parse_segment(line, frozenset())

    def _parse_segment(self, text: str, active_tags: frozenset):
        if not text:
            return

        patterns = [
            (re.compile(r'==(#[0-9A-Fa-f]{6})==(.*?)==', re.DOTALL), "highlight"),
            (re.compile(r'\*\*\*(.*?)\*\*\*', re.DOTALL),  "bold_italic"),
            (re.compile(r'\*\*(.*?)\*\*', re.DOTALL),      "bold"),
            (re.compile(r'\*([^\*]+?)\*', re.DOTALL),       "italic"),
            (re.compile(r'~~(.*?)~~', re.DOTALL),           "strikethrough"),
        ]

        earliest_match = None
        earliest_pattern_type = None

        for pat, ptype in patterns:
            m = pat.search(text)
            if m and (earliest_match is None or m.start() < earliest_match.start()):
                earliest_match = m
                earliest_pattern_type = ptype

        if earliest_match is None:
            self._insert_text(text, active_tags)
            return

        if earliest_match.start() > 0:
            self._insert_text(text[:earliest_match.start()], active_tags)

        if earliest_pattern_type == "highlight":
            color  = earliest_match.group(1)
            inner  = earliest_match.group(2)
            hl_tag = f"hl_{color.replace('#', 'hex')}"
            if hl_tag not in self.preview_text.tag_names():
                self.preview_text.tag_configure(
                    hl_tag, background=color, foreground="#1a1a2e"
                )
            new_tags = active_tags | {hl_tag}
        else:
            inner    = earliest_match.group(1)
            new_tags = active_tags | {earliest_pattern_type}

        self._parse_segment(inner, new_tags)

        rest = text[earliest_match.end():]
        if rest:
            self._parse_segment(rest, active_tags)

    def _insert_text(self, text: str, tags: frozenset):
        if not text:
            return
        tag_list = list(tags)
        if not tag_list:
            self.preview_text.insert("end", text)
            return
        combo_key = "_".join(sorted(tag_list))
        if combo_key not in self.preview_text.tag_names():
            self._configure_combo_tag(combo_key, tag_list)
        self.preview_text.insert("end", text, combo_key)

    def _configure_combo_tag(self, combo_key: str, tag_list: list):
        font_bold   = "bold"          in tag_list or "bold_italic" in tag_list
        font_italic = "italic"        in tag_list or "bold_italic" in tag_list
        overstrike  = "strikethrough" in tag_list

        if font_bold and font_italic:
            font = ("Segoe UI", 10, "bold italic")
        elif font_bold:
            font = ("Segoe UI", 10, "bold")
        elif font_italic:
            font = ("Segoe UI", 10, "italic")
        else:
            font = ("Segoe UI", 10)

        hl_tag = next((t for t in tag_list if t.startswith("hl_")), None)
        bg_color = None
        if hl_tag:
            hex_color = hl_tag.replace("hl_hex", "#").replace("hl_", "#")
            bg_color = hex_color

        kwargs = {"font": font, "overstrike": overstrike}
        if bg_color:
            kwargs["background"] = bg_color
            kwargs["foreground"] = "#1a1a2e"

        self.preview_text.tag_configure(combo_key, **kwargs)

    def _wrap_selection(self, marker_open: str, marker_close: str = None):
        if marker_close is None:
            marker_close = marker_open
        try:
            sel_start = self.editor_text.index("sel.first")
            sel_end   = self.editor_text.index("sel.last")
            selected  = self.editor_text.get(sel_start, sel_end)
            self.editor_text.delete(sel_start, sel_end)
            self.editor_text.insert(sel_start, f"{marker_open}{selected}{marker_close}")
        except tk.TclError:
            self.editor_text.insert("insert", f"{marker_open}text{marker_close}")

    def _fmt_bold(self):    self._wrap_selection("**")
    def _fmt_italic(self):  self._wrap_selection("*")
    def _fmt_strike(self):  self._wrap_selection("~~")

    def _fmt_highlight(self):
        picker = HighlightColorPicker(self.window, HIGHLIGHT_COLORS)
        self.window.wait_window(picker.window)
        if picker.result:
            self._wrap_selection(f"=={picker.result}==", "==")


# ---------------------------------------------------------------------------
# Background Color Picker
# ---------------------------------------------------------------------------

class HighlightColorPicker:
    def __init__(self, parent, colors: list):
        self.result = None

        self.window = tk.Toplevel(parent)
        self.window.title("Select Background Color")
        self.window.configure(bg=COLORS["bg"])
        self.window.geometry("320x100")
        self.window.resizable(False, False)
        self.window.grab_set()

        tk.Label(
            self.window, text="Select Color:",
            font=FONT_BODY, bg=COLORS["bg"], fg=COLORS["text"],
            padx=12, pady=8
        ).pack(anchor="w")

        row = tk.Frame(self.window, bg=COLORS["bg"])
        row.pack(padx=12)

        for hex_color, name in colors:
            swatch = tk.Label(
                row, text="  ", bg=hex_color,
                width=4, relief="flat", cursor="hand2",
                padx=2, pady=10
            )
            swatch.pack(side="left", padx=3)
            _make_tooltip(swatch, name)
            swatch.bind("<Button-1>", lambda e, c=hex_color: self._pick(c))

        self.window.bind("<Escape>", lambda e: self.window.destroy())

    def _pick(self, color: str):
        self.result = color
        self.window.destroy()


# ---------------------------------------------------------------------------
# Dialog: Edit Link
# ---------------------------------------------------------------------------

class LinkEditDialog:
    def __init__(self, parent, link: dict):
        self.result = None

        self.window = tk.Toplevel(parent)
        self.window.title("Edit Link")
        self.window.configure(bg=COLORS["bg"])
        self.window.geometry("460x200")
        self.window.resizable(False, False)
        self.window.grab_set()

        tk.Label(self.window, text="Edit Link", font=FONT_HEADING,
                 bg=COLORS["bg"], fg=COLORS["accent"],
                 pady=12, padx=20).pack(anchor="w")
        tk.Frame(self.window, bg=COLORS["accent"], height=1).pack(fill="x")

        form = tk.Frame(self.window, bg=COLORS["bg"], padx=20, pady=14)
        form.pack(fill="both", expand=True)

        tk.Label(form, text="Label", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w")
        self.label_var = tk.StringVar(value=link["label"])
        entry_label = tk.Entry(form, textvariable=self.label_var, font=FONT_BODY,
                               bg=COLORS["card"], fg=COLORS["text"],
                               insertbackground=COLORS["text"], relief="flat")
        entry_label.pack(fill="x", ipady=5, pady=(2, 10))
        entry_label.focus_set()
        entry_label.select_range(0, "end")

        tk.Label(form, text="Path", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w")
        self.path_var = tk.StringVar(value=link["path"])
        entry_path = tk.Entry(form, textvariable=self.path_var, font=FONT_BODY,
                              bg=COLORS["card"], fg=COLORS["text"],
                              insertbackground=COLORS["text"], relief="flat")
        entry_path.pack(fill="x", ipady=5, pady=(2, 14))

        btn_row = tk.Frame(form, bg=COLORS["bg"])
        btn_row.pack(fill="x")

        cancel = tk.Label(btn_row, text="Cancel", font=FONT_BODY,
                          bg=COLORS["btn_secondary"], fg=COLORS["text_dim"],
                          padx=10, pady=6, cursor="hand2")
        cancel.pack(side="right", padx=(8, 0))
        cancel.bind("<Button-1>", lambda e: self.window.destroy())

        save = tk.Label(btn_row, text="Save", font=("Segoe UI", 10, "bold"),
                        bg=COLORS["btn"], fg="white",
                        padx=10, pady=6, cursor="hand2")
        save.pack(side="right")
        save.bind("<Button-1>", lambda e: self._save())
        save.bind("<Enter>", lambda e: save.config(bg=COLORS["btn_hover"]))
        save.bind("<Leave>", lambda e: save.config(bg=COLORS["btn"]))

        self.window.bind("<Return>", lambda e: self._save())
        self.window.bind("<Escape>", lambda e: self.window.destroy())

    def _save(self):
        label = self.label_var.get().strip()
        path  = self.path_var.get().strip()
        if not label or not path:
            return
        self.result = {"label": label, "path": path}
        self.window.destroy()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _note_preview(content: str, max_lines: int = 2, max_chars: int = 78) -> str:
    """Returns a preview of the note content: max_lines lines of max_chars characters.
    Removes markdown tags before displaying."""
    if not content:
        return ""
    # Delete markdown tags
    text = re.sub(r'\*\*\*(.*?)\*\*\*', r'\1', content)
    text = re.sub(r'\*\*(.*?)\*\*',     r'\1', text)
    text = re.sub(r'\*(.*?)\*',         r'\1', text)
    text = re.sub(r'~~(.*?)~~',         r'\1', text)
    text = re.sub(r'==(#[0-9A-Fa-f]{6})==(.*?)==', r'\2', text)

    lines = [l for l in text.split('\n') if l.strip()]
    preview = []
    for line in lines[:max_lines]:
        if len(line) > max_chars:
            line = line[:max_chars - 1] + "…"
        preview.append(line)
    return '\n'.join(preview)

def _editor_alive(editor) -> bool:
    try:
        return bool(editor.window.winfo_exists())
    except Exception:
        return False


def _set_bg(widget, color: str):
    """Recursively sets the background color of a widget and its children."""
    try:
        widget.configure(bg=color)
    except tk.TclError:
        pass
    for child in widget.winfo_children():
        try:
            child.configure(bg=color)
        except tk.TclError:
            pass


def _make_tooltip(widget, text: str):
    tip_window = None

    def show(e):
        nonlocal tip_window
        x = widget.winfo_rootx() + 10
        y = widget.winfo_rooty() + widget.winfo_height() + 4
        tip_window = tk.Toplevel(widget)
        tip_window.wm_overrideredirect(True)
        tip_window.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tip_window, text=text,
            font=FONT_SMALL, bg="#ffffe0", fg="#1a1a2e",
            relief="solid", borderwidth=1, padx=6, pady=3
        ).pack()

    def hide(e):
        nonlocal tip_window
        if tip_window:
            tip_window.destroy()
            tip_window = None

    widget.bind("<Enter>", show)
    widget.bind("<Leave>", hide)


def _open_path(path: str, link_type: str):
    try:
        os.startfile(path)
    except Exception as ex:
        messagebox.showerror("Error", f"Can't be opened:\n{path}\n\n{ex}")
