# main_window.pyw

import os
import tkinter as tk
from tkinter import ttk, messagebox
from database import (
    init_db, backup_db, verify_db,
    get_all_tasks, get_on_hold_tasks,
    create_task, set_on_hold, get_task_progress,
    get_task_checkpoint_status, get_last_activity
)
from config import (APP_TITLE, MAIN_WINDOW_SIZE, STATUS_COLORS, CHECKPOINTS,
                    DEFAULT_CHECKPOINT, DB_PATH, DB_CHECK_INTERVAL_MS)
from archive import export_task_to_zip, import_task_from_zip, list_archive, remove_archived_task
from backup import create_backup, list_backups, delete_backup, restore_backup
from theme import load_theme, get_colors, SettingsDialog

# Load theme on module import
load_theme()

# COLORS is a reference to the active theme dictionary — updated in place by set_theme()
COLORS = get_colors()

FONT_TITLE   = ("Segoe UI", 20, "bold")
FONT_HEADING = ("Segoe UI", 12, "bold")
FONT_BODY    = ("Segoe UI", 10)
FONT_SMALL   = ("Segoe UI", 8)

SORT_OPTIONS = [
    ("Last activity",  "last_activity"),
    ("Creation date",   "created_at"),
    ("Progress",            "progress"),
    ("Title A–Z",         "title"),
]

# Refresh interval of the tasks list in ms
AUTO_REFRESH_MS = 5000


# ---------------------------------------------------------------------------
# Helper: mouse wheel scrolling
# ---------------------------------------------------------------------------

def _enable_mousewheel_scroll(root):
    """One mouse wheel handler for the whole application.
    The wheel scrolls the list which is under the cursor — in any window of the
    application, also in one which is in the background. A window covered by
    another one is not under the cursor, so it is never scrolled."""
    def _scroll(event):
        try:
            widget = root.winfo_containing(event.x_root, event.y_root)
        except Exception:
            return
        steps = int(-1 * (event.delta / 120))
        if steps == 0:
            steps = -1 if event.delta > 0 else 1

        while widget is not None:
            if isinstance(widget, tk.Text):
                # Text widget scrolls itself when the event is addressed to it
                if widget is not event.widget:
                    widget.yview_scroll(steps, "units")
                return
            if isinstance(widget, tk.Canvas):
                # Nothing to scroll when the whole content is visible
                if widget.yview() != (0.0, 1.0):
                    widget.yview_scroll(steps, "units")
                return
            widget = widget.master

    root.bind_all("<MouseWheel>", _scroll)


def _rebuild_window(win):
    """Builds content of a window again, with colors of the active theme.
    The window itself stays open."""
    for w in win.window.winfo_children():
        w.destroy()
    win.window.configure(bg=COLORS["bg"])
    win._build_ui()


def _window_alive(win) -> bool:
    try:
        return bool(win.window.winfo_exists())
    except Exception:
        return False


class MainWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry(MAIN_WINDOW_SIZE)
        self.root.configure(bg=COLORS["bg"])
        self.root.minsize(700, 450)

        self._task_windows = {}   # task_id -> TaskWindow
        self._aux_windows  = []   # On Hold / Archive / Backup windows
        self._cards        = {}   # task_id -> widgets and state of the task card
        self._card_order   = []   # task ids in the order of cards on the list
        self._db_error_shown = False

        # Check the database before anything is read from it
        db_status = verify_db()
        if db_status == "failed":
            messagebox.showerror(
                "Database Error",
                "The database is damaged and there is no working copy to restore it from.\n\n"
                f"{DB_PATH}\n\n"
                "The application will be closed.",
                parent=root
            )
            root.after(100, root.destroy)
            return

        init_db()
        backup_db()
        _enable_mousewheel_scroll(self.root)
        self._build_ui()
        self._load_tasks()
        self._start_auto_refresh()
        self.root.after(DB_CHECK_INTERVAL_MS, self._check_db)
        self.root.protocol("WM_DELETE_WINDOW", self._on_app_close)

        if db_status == "restored":
            self.root.after(300, self._show_db_restored)

    def _build_ui(self):
        header = tk.Frame(self.root, bg=COLORS["panel"])
        header.pack(fill="x", side="top")

        tk.Label(
            header, text=f"◈  {APP_TITLE.upper()}",
            font=FONT_TITLE, bg=COLORS["panel"],
            fg=COLORS["accent"], padx=20, pady=14
        ).pack(side="left")

        self._make_button(header, "+ New task",  lambda: self._new_task(),
                          side="right", padx=20, pady=12)
        self._make_button(header, "📦 Archive",  lambda: self._open_archive(),
                          side="right", padx=(0, 4), pady=12, secondary=True)
        self._make_button(header, "⏸ On Hold",    lambda: self._open_on_hold(),
                          side="right", padx=(0, 4), pady=12, secondary=True)
        self._make_button(header, "💾 Backup",    lambda: self._open_backup(),
                          side="right", padx=(0, 4), pady=12, secondary=True)
        self._make_button(header, "⚙ Settings",  lambda: self._open_settings(),
                          side="right", padx=(0, 4), pady=12, secondary=True)

        tk.Frame(self.root, bg=COLORS["accent"], height=2).pack(fill="x")

        filter_bar = tk.Frame(self.root, bg=COLORS["bg"], padx=16, pady=10)
        filter_bar.pack(fill="x")

        tk.Label(filter_bar, text="Search:", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text_dim"]).pack(side="left")

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._load_tasks())
        tk.Entry(
            filter_bar, textvariable=self.search_var,
            font=FONT_BODY, bg=COLORS["card"], fg=COLORS["text"],
            insertbackground=COLORS["text"], relief="flat", width=28
        ).pack(side="left", padx=(6, 20), ipady=4)

        # Sorting
        tk.Label(filter_bar, text="Sort by:", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text_dim"]).pack(side="left")

        self.sort_var = tk.StringVar(value=SORT_OPTIONS[0][0])
        sort_cb = ttk.Combobox(
            filter_bar, textvariable=self.sort_var,
            values=[opt[0] for opt in SORT_OPTIONS],
            state="readonly", width=18, font=FONT_BODY
        )
        sort_cb.pack(side="left", padx=(6, 0), ipady=2)
        sort_cb.bind("<<ComboboxSelected>>", lambda e: self._load_tasks())

        # Combobox style for the active theme
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox",
            fieldbackground=COLORS["card"],
            background=COLORS["card"],
            foreground=COLORS["text"],
            selectbackground=COLORS["card_hover"],
            selectforeground=COLORS["text"],
            bordercolor=COLORS["border"],
            arrowcolor=COLORS["text_dim"],
        )

        self.count_label = tk.Label(filter_bar, text="", font=FONT_SMALL,
                                    bg=COLORS["bg"], fg=COLORS["text_dim"])
        self.count_label.pack(side="right")

        list_frame = tk.Frame(self.root, bg=COLORS["bg"])
        list_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self.canvas = tk.Canvas(list_frame, bg=COLORS["bg"], highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.cards_frame = tk.Frame(self.canvas, bg=COLORS["bg"])
        self.canvas_window = self.canvas.create_window(
            (0, 0), window=self.cards_frame, anchor="nw"
        )
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.cards_frame.bind("<Configure>", self._on_frame_configure)

    # -----------------------------------------------------------------------
    # Loading tasks
    # -----------------------------------------------------------------------

    def _get_sort_key(self) -> str:
        label = self.sort_var.get()
        for opt_label, opt_key in SORT_OPTIONS:
            if opt_label == label:
                return opt_key
        return "last_activity"

    def _get_task_state(self, task: dict) -> dict:
        """Returns everything what is shown on the task card besides the task record itself."""
        done, total = get_task_progress(task["id"])
        return {
            "done":          done,
            "total":         total,
            "status":        get_task_checkpoint_status(task["id"]),
            "last_activity": get_last_activity(task["id"]),
        }

    def _get_sorted_tasks(self) -> list:
        """Returns list of (task, state) filtered and sorted according to the filter bar."""
        query    = self.search_var.get().lower()
        sort_key = self._get_sort_key()

        tasks = get_all_tasks()   # default: created_at DESC

        if query:
            tasks = [t for t in tasks if query in t["title"].lower()
                     or query in (t["description"] or "").lower()]

        items = [(t, self._get_task_state(t)) for t in tasks]

        if sort_key == "last_activity":
            items.sort(key=lambda i: i[1]["last_activity"], reverse=True)
        elif sort_key == "created_at":
            items.sort(key=lambda i: i[0]["created_at"], reverse=True)
        elif sort_key == "progress":
            items.sort(key=lambda i: i[1]["done"] / i[1]["total"] if i[1]["total"] else 0.0,
                       reverse=True)
        elif sort_key == "title":
            items.sort(key=lambda i: i[0]["title"].lower())

        return items

    def _load_tasks(self):
        """Builds the whole list of task cards from scratch."""
        self._build_cards(self._get_sorted_tasks())

    def _build_cards(self, items: list):
        for w in self.cards_frame.winfo_children():
            w.destroy()
        self._cards = {}
        self._card_order = [task["id"] for task, _ in items]

        self.count_label.config(text=f"{len(items)} task{'s' if len(items) != 1 else ''}")

        if not items:
            tk.Label(
                self.cards_frame,
                text="No tasks available. Click '+ New task' to add the first one.",
                font=FONT_BODY, bg=COLORS["bg"], fg=COLORS["text_dim"], pady=40
            ).pack()
            return

        for task, state in items:
            self._make_task_card(task, state)

    def _refresh_tasks(self):
        """Refreshes the list without rebuilding it. Cards are built again only when
        the set of tasks, their order, title or description changed; otherwise only
        the changed values are updated in the existing cards, so nothing blinks."""
        items = self._get_sorted_tasks()

        if [task["id"] for task, _ in items] != self._card_order:
            self._build_cards(items)
            return

        for task, state in items:
            card = self._cards[task["id"]]
            if (task["title"], task["description"]) != (card["title"], card["description"]):
                self._build_cards(items)
                return
            if state != card["state"]:
                self._update_task_card(task, state)

    @staticmethod
    def _status_color(state: dict) -> str:
        if state["done"] == 0:
            return STATUS_COLORS["not_started"]
        if state["done"] == state["total"]:
            return STATUS_COLORS["completed"]
        return STATUS_COLORS["in_progress"]

    @staticmethod
    def _activity_text(state: dict) -> str:
        last_act = state["last_activity"]
        return "last activity: " + (last_act[:16].replace("T", "  ") if last_act else "")

    def _make_task_card(self, task: dict, state: dict):
        card = tk.Frame(self.cards_frame, bg=COLORS["card"], pady=12, padx=14)
        card.pack(fill="x", pady=4, padx=2)

        status_bar = tk.Frame(card, bg=self._status_color(state), width=4)
        status_bar.pack(side="left", fill="y", padx=(0, 12))

        info = tk.Frame(card, bg=COLORS["card"])
        info.pack(side="left", fill="both", expand=True)

        row1 = tk.Frame(info, bg=COLORS["card"])
        row1.pack(fill="x")
        tk.Label(row1, text=task["title"], font=FONT_HEADING,
                 bg=COLORS["card"], fg=COLORS["text"], anchor="w").pack(side="left")
        tk.Label(row1, text=task["created_at"][:10], font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"]).pack(side="right")

        if task["description"]:
            desc = task["description"]
            if len(desc) > 80:
                desc = desc[:77] + "..."
            tk.Label(info, text=desc, font=FONT_SMALL,
                     bg=COLORS["card"], fg=COLORS["text_dim"], anchor="w").pack(fill="x", pady=(2, 4))

        progress_frame = tk.Frame(info, bg=COLORS["progress_bg"], height=4)
        progress_frame.pack(fill="x", pady=(4, 2))
        progress_frame.pack_propagate(False)
        progress_fill = tk.Frame(progress_frame, bg=COLORS["progress_fg"])

        bottom_row = tk.Frame(info, bg=COLORS["card"])
        bottom_row.pack(fill="x", pady=(2, 0))

        status_label = tk.Label(bottom_row, text="",
                                font=("Segoe UI", 8, "bold"), bg=COLORS["card"],
                                fg=COLORS["accent2"], anchor="w")
        status_label.pack(side="left")

        activity_label = tk.Label(bottom_row, text="",
                                  font=FONT_SMALL, bg=COLORS["card"],
                                  fg=COLORS["text_dim"], anchor="e")
        activity_label.pack(side="right")

        actions = tk.Frame(card, bg=COLORS["card"])
        actions.pack(side="right", padx=(12, 0))

        self._make_button(
            actions, "⏸ Put on hold",
            lambda tid=task["id"]: self._hold_task(tid),
            small=True, secondary=True, side="top", padx=2, pady=2
        )

        def open_on_click(e, tid=task["id"]):
            self._open_task(tid)

        for widget in [card, info, row1, bottom_row, progress_frame]:
            widget.bind("<Button-1>", open_on_click)
            widget.configure(cursor="hand2")

        for lbl in info.winfo_children() + row1.winfo_children() + bottom_row.winfo_children():
            try:
                lbl.bind("<Button-1>", open_on_click)
                lbl.configure(cursor="hand2")
            except Exception:
                pass

        self._bind_hover(card, COLORS["card"], COLORS["card_hover"],
                         exclude=[status_bar, progress_frame, actions])

        # References to the parts of the card which change — used by _update_task_card
        self._cards[task["id"]] = {
            "title":          task["title"],
            "description":    task["description"],
            "state":          None,
            "status_bar":     status_bar,
            "progress_fill":  progress_fill,
            "status_label":   status_label,
            "activity_label": activity_label,
            "actions":        actions,
            "archive_btn":    None,
        }
        self._update_task_card(task, state)

    def _update_task_card(self, task: dict, state: dict):
        """Puts current values into an existing task card."""
        card = self._cards[task["id"]]
        is_finished = (state["done"] == state["total"] and state["total"] > 0)

        card["status_bar"].config(bg=self._status_color(state))

        if state["done"] > 0 and state["total"]:
            card["progress_fill"].place(relwidth=state["done"] / state["total"], relheight=1.0)
        else:
            card["progress_fill"].place_forget()

        card["status_label"].config(text=state["status"])
        card["activity_label"].config(text=self._activity_text(state))

        # Archive button is available only for a finished task
        if is_finished and card["archive_btn"] is None:
            card["archive_btn"] = self._make_button(
                card["actions"], "📦 Archive",
                lambda tid=task["id"], ttl=task["title"]: self._archive_task(tid, ttl, "active"),
                small=True, secondary=True, side="top", padx=2, pady=2
            )
        elif not is_finished and card["archive_btn"] is not None:
            card["archive_btn"].destroy()
            card["archive_btn"] = None

        card["state"] = state

    # -----------------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------------

    def _new_task(self):
        dialog = NewTaskDialog(self.root)
        self.root.wait_window(dialog.window)
        if dialog.result:
            checkpoints = None if dialog.result.get("use_template") else []
            create_task(dialog.result["title"], dialog.result["description"], checkpoints=checkpoints)
            self._load_tasks()

    def _open_task(self, task_id: int):
        from task_window import TaskWindow

        # If the task is already open — give it focus
        tw = self._task_windows.get(task_id)
        if tw is not None:
            if _window_alive(tw):
                tw.window.lift()
                tw.window.focus_force()
                return
            del self._task_windows[task_id]

        def on_task_close(tid=task_id):
            self._task_windows.pop(tid, None)
            self._refresh_tasks()

        tw = TaskWindow(self.root, task_id, on_close=on_task_close)
        if _window_alive(tw):
            self._task_windows[task_id] = tw

    def _close_task_window(self, task_id: int):
        """Closes window of the task if it is open. Unsaved notes are saved first."""
        tw = self._task_windows.pop(task_id, None)
        if tw is not None and _window_alive(tw):
            tw.close()

    def _hold_task(self, task_id: int):
        set_on_hold(task_id, True)
        self._load_tasks()

    def _archive_task(self, task_id: int, title: str, source: str):
        if not messagebox.askyesno(
            "Archive Task",
            f"Are you sure you want to archive the task:\n\n\"{title}\"\n\n"
            f"The task will be removed from the database and saved as a ZIP file in the archive folder.",
            parent=self.root
        ):
            return
        try:
            self._close_task_window(task_id)
            zip_path = export_task_to_zip(task_id, source)
            self._load_tasks()
            messagebox.showinfo(
                "Archived",
                f"Task has been archived:\n{zip_path}",
                parent=self.root
            )
        except Exception as e:
            messagebox.showerror("Error", f"Failed to archive task:\n{e}", parent=self.root)

    def _open_backup(self):
        self._aux_windows.append(BackupWindow(self.root, on_restore=self._load_tasks))

    def _open_settings(self):
        SettingsDialog(self.root, on_theme_change=self._apply_theme)

    def _apply_theme(self):
        """Builds content of all open windows again with colors of the new theme.
        No window is closed and nothing typed in is lost."""
        search, sort_label = self.search_var.get(), self.sort_var.get()

        for w in self.root.winfo_children():
            if not isinstance(w, tk.Toplevel):
                w.destroy()
        self.root.configure(bg=COLORS["bg"])
        self._build_ui()
        self.sort_var.set(sort_label)
        self.search_var.set(search)   # loads the list of tasks as well

        for tw in list(self._task_windows.values()):
            if _window_alive(tw):
                tw.rebuild()

        self._aux_windows = [w for w in self._aux_windows if _window_alive(w)]
        for win in self._aux_windows:
            _rebuild_window(win)

    def _open_on_hold(self):
        self._aux_windows.append(OnHoldWindow(
            self.root, on_restore=self._load_tasks, on_archive=self._load_tasks,
            before_archive=self._close_task_window))

    def _open_archive(self):
        self._aux_windows.append(ArchiveWindow(self.root, on_restore=self._load_tasks))

    def _start_auto_refresh(self):
        # Next refresh is planned first — an error below does not stop refreshing
        self.root.after(AUTO_REFRESH_MS, self._start_auto_refresh)

        # Clear expired references
        dead = [tid for tid, tw in self._task_windows.items() if not _window_alive(tw)]
        for tid in dead:
            del self._task_windows[tid]
        self._aux_windows = [w for w in self._aux_windows if _window_alive(w)]

        self._refresh_tasks()

    # -----------------------------------------------------------------------
    # Database check
    # -----------------------------------------------------------------------

    def _check_db(self):
        """Periodic check of the database. A database which is fine is saved as the
        last working copy; a damaged one is restored from that copy."""
        self.root.after(DB_CHECK_INTERVAL_MS, self._check_db)

        db_status = verify_db()
        if db_status == "ok":
            backup_db()
            self._db_error_shown = False
        elif db_status == "restored":
            init_db()
            self._reload_after_db_change()
            self._show_db_restored()
        elif not self._db_error_shown:
            self._db_error_shown = True
            messagebox.showerror(
                "Database Error",
                "The database is damaged and there is no working copy to restore it from.\n\n"
                f"{DB_PATH}",
                parent=self.root
            )

    def _show_db_restored(self):
        messagebox.showwarning(
            "Database Restored",
            "The database was damaged and has been restored from the last working copy.\n\n"
            "Changes made after the last check of the database may be missing.\n"
            "The damaged file was kept next to the database (tasks.db.corrupt_...).",
            parent=self.root
        )

    def _reload_after_db_change(self):
        """Reloads everything shown after the database content was replaced."""
        for task_id, tw in list(self._task_windows.items()):
            if _window_alive(tw):
                tw.reload()
            if not _window_alive(tw):
                self._task_windows.pop(task_id, None)
        self._load_tasks()
        self._aux_windows = [w for w in self._aux_windows if _window_alive(w)]
        for win in self._aux_windows:
            _rebuild_window(win)

    def _on_app_close(self):
        """Closing the application: unsaved notes are saved, the database is checked
        and saved as the last working copy."""
        for tw in list(self._task_windows.values()):
            if _window_alive(tw):
                try:
                    tw.save_open_notes()
                except Exception:
                    pass
        backup_db()
        self.root.destroy()

    # -----------------------------------------------------------------------
    # UI helpers
    # -----------------------------------------------------------------------

    def _make_button(self, parent, text, command,
                     side="left", padx=4, pady=4,
                     small=False, secondary=False):
        font     = FONT_SMALL if small else FONT_BODY
        bg       = COLORS["btn_secondary"] if secondary else COLORS["btn"]
        fg       = COLORS["text_dim"]      if secondary else "white"
        hover_bg = COLORS["btn_sec_hover"] if secondary else COLORS["btn_hover"]

        btn = tk.Label(parent, text=text, font=font, bg=bg, fg=fg,
                       padx=8 if small else 14, pady=4 if small else 6,
                       cursor="hand2", relief="flat")
        btn.pack(side=side, padx=padx, pady=pady)
        btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg))
        btn.bind("<Leave>", lambda e: btn.config(bg=bg))
        return btn

    def _bind_hover(self, widget, color_normal, color_hover, exclude=()):
        """Changes background of the widget and everything inside it while the cursor
        is over it. Widgets from exclude (and their content) keep their own colors."""
        def set_color(w, color):
            try:
                w.config(bg=color)
            except Exception:
                pass
            for child in w.winfo_children():
                if child not in exclude:
                    set_color(child, color)

        def on_enter(e):
            set_color(widget, color_hover)

        def on_leave(e):
            # Moving the cursor onto a child of the widget is not leaving it
            try:
                under = str(widget.winfo_containing(*widget.winfo_pointerxy()) or "")
            except Exception:
                under = ""
            if under == str(widget) or under.startswith(str(widget) + "."):
                return
            set_color(widget, color_normal)

        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)

    def _on_canvas_resize(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))


# ---------------------------------------------------------------------------
# Dialog: New task
# ---------------------------------------------------------------------------

class NewTaskDialog:
    def __init__(self, parent):
        self.result = None
        self.window = tk.Toplevel(parent)
        self.window.title("New Task")
        self.window.configure(bg=COLORS["bg"])
        self.window.geometry("460x360")
        self.window.resizable(False, False)
        self.window.grab_set()

        tk.Label(self.window, text="New Task", font=("Segoe UI", 12, "bold"),
                 bg=COLORS["bg"], fg=COLORS["accent"], pady=12).pack()
        tk.Frame(self.window, bg=COLORS["accent"], height=1).pack(fill="x")

        form = tk.Frame(self.window, bg=COLORS["bg"], padx=24, pady=16)
        form.pack(fill="both", expand=True)

        tk.Label(form, text="Title *", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w")
        self.title_var = tk.StringVar()
        title_entry = tk.Entry(form, textvariable=self.title_var,
                               font=FONT_BODY, bg=COLORS["card"], fg=COLORS["text"],
                               insertbackground=COLORS["text"], relief="flat")
        title_entry.pack(fill="x", ipady=5, pady=(2, 12))
        title_entry.focus_set()

        tk.Label(form, text="Short Description (Optional)", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w")
        self.desc_text = tk.Text(form, height=3, font=FONT_BODY,
                                 bg=COLORS["card"], fg=COLORS["text"],
                                 insertbackground=COLORS["text"], relief="flat", wrap="word")
        self.desc_text.pack(fill="x", pady=(2, 12))

        tk.Label(form, text="Kanban", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w")
        self.template_var = tk.StringVar(value="template")
        tmpl_frame = tk.Frame(form, bg=COLORS["bg"])
        tmpl_frame.pack(anchor="w", pady=(2, 14))
        radio_style = dict(
            bg=COLORS["bg"], fg=COLORS["text"],
            activebackground=COLORS["bg"], activeforeground=COLORS["text"],
            selectcolor=COLORS["card"], font=FONT_BODY
        )
        tk.Radiobutton(
            tmpl_frame, text=f"Use Default Template  ({len(CHECKPOINTS)} Checkpoints)",
            variable=self.template_var, value="template", **radio_style
        ).pack(anchor="w")
        tk.Radiobutton(
            tmpl_frame, text=f"Empty Kanban  (\"{DEFAULT_CHECKPOINT['name']}\" checkpoint only)",
            variable=self.template_var, value="empty", **radio_style
        ).pack(anchor="w")

        btn_row = tk.Frame(form, bg=COLORS["bg"])
        btn_row.pack(fill="x")
        confirm = tk.Label(btn_row, text="Create Task",
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
            "title":        title,
            "description":  self.desc_text.get("1.0", "end").strip(),
            "use_template": self.template_var.get() == "template",
        }
        self.window.destroy()


# ---------------------------------------------------------------------------
# Window: On Hold
# ---------------------------------------------------------------------------

class OnHoldWindow:
    def __init__(self, parent, on_restore=None, on_archive=None, before_archive=None):
        self.on_restore = on_restore
        self.on_archive = on_archive
        self.before_archive = before_archive   # function(task_id) called before a task is archived

        self.window = tk.Toplevel(parent)
        self.window.title("On Hold")
        self.window.configure(bg=COLORS["bg"])
        self.window.geometry("700x480")
        self.window.minsize(500, 300)

        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self.window, bg=COLORS["panel"])
        header.pack(fill="x")
        tk.Label(header, text="⏸  ON HOLD", font=FONT_TITLE,
                 bg=COLORS["panel"], fg=COLORS["text_dim"],
                 padx=20, pady=14).pack(side="left")
        tk.Frame(self.window, bg=COLORS["accent"], height=2).pack(fill="x")

        list_frame = tk.Frame(self.window, bg=COLORS["bg"])
        list_frame.pack(fill="both", expand=True, padx=16, pady=12)

        self.canvas = tk.Canvas(list_frame, bg=COLORS["bg"], highlightthickness=0, bd=0)
        sb = tk.Scrollbar(list_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.cards_frame = tk.Frame(self.canvas, bg=COLORS["bg"])
        cw = self.canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(cw, width=e.width))
        self.cards_frame.bind("<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        self._load()

    def _load(self):
        for w in self.cards_frame.winfo_children():
            w.destroy()

        tasks = get_on_hold_tasks()
        if not tasks:
            tk.Label(self.cards_frame, text="No tasks on hold.",
                     font=FONT_BODY, bg=COLORS["bg"], fg=COLORS["text_dim"],
                     pady=40).pack()
            return

        for task in tasks:
            self._make_card(task)

    def _make_card(self, task: dict):
        done, total = get_task_progress(task["id"])

        card = tk.Frame(self.cards_frame, bg=COLORS["card"], pady=10, padx=14)
        card.pack(fill="x", pady=4, padx=2)

        tk.Frame(card, bg=COLORS["text_dim"], width=4).pack(side="left", fill="y", padx=(0, 12))

        info = tk.Frame(card, bg=COLORS["card"])
        info.pack(side="left", fill="both", expand=True)

        row1 = tk.Frame(info, bg=COLORS["card"])
        row1.pack(fill="x")
        tk.Label(row1, text=task["title"], font=("Segoe UI", 11, "bold"),
                 bg=COLORS["card"], fg=COLORS["text_dim"], anchor="w").pack(side="left")
        hold_date = (task["on_hold_at"] or "")[:10]
        tk.Label(row1, text=f"on hold: {hold_date}", font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"]).pack(side="right")

        tk.Label(info, text=f"{done} of {total} checkpoints completed", font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"], anchor="w").pack(anchor="w", pady=(2, 0))

        actions = tk.Frame(card, bg=COLORS["card"])
        actions.pack(side="right", padx=(12, 0))

        self._make_btn(actions, "▶ Restore",   COLORS["btn"],
                       lambda tid=task["id"]: self._restore(tid))
        self._make_btn(actions, "📦 Archive", COLORS["btn_secondary"],
                       lambda tid=task["id"], ttl=task["title"]: self._archive(tid, ttl))

    def _make_btn(self, parent, text, bg, command):
        btn = tk.Label(parent, text=text, font=FONT_SMALL, bg=bg, fg="white",
                       padx=8, pady=4, cursor="hand2")
        btn.pack(side="top", pady=2)
        btn.bind("<Button-1>", lambda e: command())
        hover = COLORS["btn_hover"] if bg == COLORS["btn"] else COLORS["btn_sec_hover"]
        btn.bind("<Enter>", lambda e: btn.config(bg=hover))
        btn.bind("<Leave>", lambda e: btn.config(bg=bg))

    def _restore(self, task_id: int):
        set_on_hold(task_id, False)
        if self.on_restore:
            self.on_restore()
        self._load()

    def _archive(self, task_id: int, title: str):
        if not messagebox.askyesno(
            "Archive Task",
            f"Are you sure you want to archive the task:\n\n\"{title}\"\n\n"
            f"The task will be deleted from the database and saved as a ZIP file.",
            parent=self.window
        ):
            return
        try:
            if self.before_archive:
                self.before_archive(task_id)
            zip_path = export_task_to_zip(task_id, "onhold")
            if self.on_archive:
                self.on_archive()
            self._load()
            messagebox.showinfo("Task Archived",
                                f"Task has been archived:\n{zip_path}",
                                parent=self.window)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to archive task:\n{e}",
                                 parent=self.window)


# ---------------------------------------------------------------------------
# Window: Backup
# ---------------------------------------------------------------------------

class BackupWindow:
    def __init__(self, parent, on_restore=None):
        self.on_restore = on_restore

        self.window = tk.Toplevel(parent)
        self.window.title("Backup")
        self.window.configure(bg=COLORS["bg"])
        self.window.geometry("720x500")
        self.window.minsize(560, 360)

        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self.window, bg=COLORS["panel"])
        header.pack(fill="x")
        tk.Label(header, text="💾  BACKUP", font=FONT_TITLE,
                 bg=COLORS["panel"], fg=COLORS["accent"],
                 padx=20, pady=14).pack(side="left")

        # Create backup button
        create_btn = tk.Label(
            header, text="+ Create backup", font=FONT_BODY,
            bg=COLORS["btn"], fg="white",
            padx=14, pady=6, cursor="hand2"
        )
        create_btn.pack(side="right", padx=12, pady=12)
        create_btn.bind("<Button-1>", lambda e: self._create_backup(create_btn))
        create_btn.bind("<Enter>", lambda e: create_btn.config(bg=COLORS["btn_hover"]))
        create_btn.bind("<Leave>", lambda e: create_btn.config(bg=COLORS["btn"]))

        tk.Frame(self.window, bg=COLORS["accent"], height=2).pack(fill="x")

        # Status bar (backup progress)
        self.status_bar = tk.Frame(self.window, bg=COLORS["panel"])
        self.status_label = tk.Label(
            self.status_bar, text="", font=FONT_SMALL,
            bg=COLORS["panel"], fg=COLORS["text_dim"], padx=16, pady=6
        )
        self.status_label.pack(side="left")

        # Backups list
        self.list_frame = tk.Frame(self.window, bg=COLORS["bg"])
        self.list_frame.pack(fill="both", expand=True, padx=16, pady=12)

        self.canvas = tk.Canvas(self.list_frame, bg=COLORS["bg"], highlightthickness=0, bd=0)
        sb = tk.Scrollbar(self.list_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.cards_frame = tk.Frame(self.canvas, bg=COLORS["bg"])
        cw = self.canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(cw, width=e.width))
        self.cards_frame.bind("<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        self._load()

    def _load(self):
        for w in self.cards_frame.winfo_children():
            w.destroy()

        backups = list_backups()

        if not backups:
            tk.Label(
                self.cards_frame,
                text="No backups available. Click '+ Create backup' to create the first one.",
                font=FONT_BODY, bg=COLORS["bg"], fg=COLORS["text_dim"],
                pady=40
            ).pack()
            return

        for b in backups:
            self._make_card(b)

    def _make_card(self, b: dict):
        meta = b.get("meta", {})
        card = tk.Frame(self.cards_frame, bg=COLORS["card"], pady=10, padx=14)
        card.pack(fill="x", pady=3, padx=2)

        tk.Frame(card, bg=COLORS["accent2"], width=4).pack(
            side="left", fill="y", padx=(0, 12))

        info = tk.Frame(card, bg=COLORS["card"])
        info.pack(side="left", fill="both", expand=True)

        # Line 1: file name + size
        row1 = tk.Frame(info, bg=COLORS["card"])
        row1.pack(fill="x")
        tk.Label(row1, text=b["filename"], font=FONT_BODY,
                 bg=COLORS["card"], fg=COLORS["text"], anchor="w").pack(side="left")
        tk.Label(row1, text=f"{b['size_mb']} MB", font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"]).pack(side="right")

        # Line 2: statistics from metadata
        if meta:
            stats = (
                f"Tasks: {meta.get('tasks_active', '?')} active, "
                f"{meta.get('tasks_on_hold', '?')} on hold, "
                f"{meta.get('tasks_archived', '?')} archived  |  "
                f"Attachments: {meta.get('attachment_files', 0)} files  |  "
                f"Packed: {meta.get('packed_files', '?')} files"
            )
        else:
            stats = "No metadata"
        tk.Label(info, text=stats, font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"], anchor="w").pack(fill="x", pady=(2, 0))

        # Date
        tk.Label(info, text=f"Created: {b['date']}", font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"], anchor="w").pack(fill="x")

        # Buttons
        actions = tk.Frame(card, bg=COLORS["card"])
        actions.pack(side="right", padx=(12, 0))

        restore_btn = tk.Label(actions, text="↩ Restore", font=FONT_SMALL,
                               bg=COLORS["btn"], fg="white",
                               padx=8, pady=4, cursor="hand2")
        restore_btn.pack(pady=(0, 4))
        restore_btn.bind("<Button-1>",
            lambda e, p=b["zip_path"], fn=b["filename"]: self._restore(p, fn))
        restore_btn.bind("<Enter>", lambda e: restore_btn.config(bg=COLORS["btn_hover"]))
        restore_btn.bind("<Leave>", lambda e: restore_btn.config(bg=COLORS["btn"]))

        open_btn = tk.Label(actions, text="📂 Open folder", font=FONT_SMALL,
                            bg=COLORS["btn_secondary"], fg=COLORS["text_dim"],
                            padx=8, pady=4, cursor="hand2")
        open_btn.pack(pady=(0, 4))
        open_btn.bind("<Button-1>",
            lambda e, p=b["zip_path"]: self._open_folder(p))
        open_btn.bind("<Enter>", lambda e: open_btn.config(fg=COLORS["text"]))
        open_btn.bind("<Leave>", lambda e: open_btn.config(fg=COLORS["text_dim"]))

        del_btn = tk.Label(actions, text="🗑 Delete", font=FONT_SMALL,
                           bg="#3a1515", fg="#ff9999",
                           padx=8, pady=4, cursor="hand2")
        del_btn.pack()
        del_btn.bind("<Button-1>",
            lambda e, p=b["zip_path"], fn=b["filename"]: self._delete(p, fn))
        del_btn.bind("<Enter>", lambda e: del_btn.config(bg="#5a2020"))
        del_btn.bind("<Leave>", lambda e: del_btn.config(bg="#3a1515"))

    def _create_backup(self, btn: tk.Label):
        """Runs backup and updates status in UI."""
        btn.config(text="⏳ Creating...", bg=COLORS["text_dim"], cursor="")
        btn.unbind("<Button-1>")

        # Show status bar
        self.status_bar.pack(fill="x", before=self.list_frame)
        self.status_label.config(text="Preparing backup...")
        self.window.update()

        def on_progress(arc_name: str, current: int, total: int):
            short = arc_name if len(arc_name) <= 60 else "..." + arc_name[-57:]
            self.status_label.config(
                text=f"Packing {current}/{total}: {short}")
            self.window.update_idletasks()

        try:
            zip_path = create_backup(progress_callback=on_progress)
            self.status_bar.pack_forget()
            self._load()
            messagebox.showinfo(
                "Backup Created",
                f"Backup has been saved:\n{zip_path}",
                parent=self.window
            )
        except Exception as ex:
            self.status_bar.pack_forget()
            messagebox.showerror(
                "Backup Error",
                f"Failed to create backup:\n{ex}",
                parent=self.window
            )
        finally:
            btn.config(text="+ Create backup", bg=COLORS["btn"], cursor="hand2")
            btn.bind("<Button-1>", lambda e: self._create_backup(btn))

    def _restore(self, zip_path: str, filename: str):
        if not messagebox.askyesno(
            "Restore Backup",
            f"Restore data from the backup?\n\n{filename}\n\n"
            "Tasks and archived tasks which are missing now will be added from the backup.\n"
            "Existing tasks will not be changed or removed.",
            parent=self.window
        ):
            return
        try:
            result = restore_backup(zip_path)
            if self.on_restore:
                self.on_restore()
            messagebox.showinfo(
                "Backup Restored",
                f"Tasks added: {result['tasks_added']}\n"
                f"Tasks already existing (skipped): {result['tasks_skipped']}\n"
                f"Archived tasks added: {result['archives_added']}",
                parent=self.window
            )
        except Exception as ex:
            messagebox.showerror(
                "Backup Error",
                f"Failed to restore backup:\n{ex}",
                parent=self.window
            )

    def _open_folder(self, zip_path: str):
        """Opens backup folder in Windows Explorer."""
        folder = os.path.dirname(zip_path)
        try:
            os.startfile(folder)
        except Exception as ex:
            messagebox.showerror("Error",
                f"Can't open folder:\n{folder}\n\n{ex}",
                parent=self.window)

    def _delete(self, zip_path: str, filename: str):
        if not messagebox.askyesno(
            "Delete Backup",
            f"Are you sure you want to delete the backup?\n\n{filename}\n\n"
            "This operation can not be undone.",
            parent=self.window
        ):
            return
        try:
            delete_backup(zip_path)
            self._load()
        except Exception as ex:
            messagebox.showerror("Error",
                f"Failed to delete backup:\n{ex}",
                parent=self.window)


# ---------------------------------------------------------------------------
# Window: Archive
# ---------------------------------------------------------------------------

class ArchiveWindow:
    def __init__(self, parent, on_restore=None):
        self.on_restore = on_restore

        self.window = tk.Toplevel(parent)
        self.window.title("Archive")
        self.window.configure(bg=COLORS["bg"])
        self.window.geometry("800x520")
        self.window.minsize(600, 350)

        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self.window, bg=COLORS["panel"])
        header.pack(fill="x")
        tk.Label(header, text="📦  ARCHIVE", font=FONT_TITLE,
                 bg=COLORS["panel"], fg=COLORS["text_dim"],
                 padx=20, pady=14).pack(side="left")
        tk.Frame(self.window, bg=COLORS["accent"], height=2).pack(fill="x")

        list_frame = tk.Frame(self.window, bg=COLORS["bg"])
        list_frame.pack(fill="both", expand=True, padx=16, pady=12)

        self.canvas = tk.Canvas(list_frame, bg=COLORS["bg"], highlightthickness=0, bd=0)
        sb = tk.Scrollbar(list_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.cards_frame = tk.Frame(self.canvas, bg=COLORS["bg"])
        cw = self.canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(cw, width=e.width))
        self.cards_frame.bind("<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        self._load()

    def _load(self):
        for w in self.cards_frame.winfo_children():
            w.destroy()

        archives = list_archive()
        onhold   = [a for a in archives if a["source"] == "onhold"]
        finished = [a for a in archives if a["source"] != "onhold"]

        if not archives:
            tk.Label(self.cards_frame, text="Archive is empty.",
                     font=FONT_BODY, bg=COLORS["bg"], fg=COLORS["text_dim"],
                     pady=40).pack()
            return

        if onhold:
            self._section_header("⏸  On Hold")
            for a in onhold:
                self._make_card(a)

        if finished:
            self._section_header("✅  Finished")
            for a in finished:
                self._make_card(a)

    def _section_header(self, text: str):
        frm = tk.Frame(self.cards_frame, bg=COLORS["bg"])
        frm.pack(fill="x", pady=(12, 4))
        tk.Label(frm, text=text, font=("Segoe UI", 11, "bold"),
                 bg=COLORS["bg"], fg=COLORS["accent"], padx=4).pack(side="left")
        tk.Frame(frm, bg=COLORS["border"], height=1).pack(
            side="left", fill="x", expand=True, padx=(8, 0), pady=6)

    def _make_card(self, a: dict):
        card = tk.Frame(self.cards_frame, bg=COLORS["card"], pady=8, padx=14)
        card.pack(fill="x", pady=3, padx=2)

        src_color = COLORS["text_dim"] if a["source"] == "onhold" else STATUS_COLORS["completed"]
        tk.Frame(card, bg=src_color, width=4).pack(side="left", fill="y", padx=(0, 12))

        info = tk.Frame(card, bg=COLORS["card"])
        info.pack(side="left", fill="both", expand=True)

        row1 = tk.Frame(info, bg=COLORS["card"])
        row1.pack(fill="x")
        tk.Label(row1, text=a["title"], font=("Segoe UI", 11, "bold"),
                 bg=COLORS["card"], fg=COLORS["text"], anchor="w").pack(side="left")
        tk.Label(row1, text=f"archived: {a['export_date']}", font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"]).pack(side="right")

        row2 = tk.Frame(info, bg=COLORS["card"])
        row2.pack(fill="x")
        tk.Label(row2,
                 text=f"Progress: {a['progress']}  |  created: {a['created_at']}",
                 font=FONT_SMALL, bg=COLORS["card"], fg=COLORS["text_dim"],
                 anchor="w").pack(side="left")

        actions = tk.Frame(card, bg=COLORS["card"])
        actions.pack(side="right", padx=(12, 0))

        restore_btn = tk.Label(actions, text="▶ Restore", font=FONT_SMALL,
                               bg=COLORS["btn"], fg="white", padx=8, pady=4, cursor="hand2")
        restore_btn.pack(pady=(0, 2))
        restore_btn.bind("<Button-1>",
            lambda e, zp=a["zip_path"], fn=a["filename"], src=a["source"]: self._restore(zp, fn, src))
        restore_btn.bind("<Enter>", lambda e: restore_btn.config(bg=COLORS["btn_hover"]))
        restore_btn.bind("<Leave>", lambda e: restore_btn.config(bg=COLORS["btn"]))

        del_btn = tk.Label(actions, text="🗑 Delete", font=FONT_SMALL,
                           bg="#3a1515", fg="#ff9999", padx=8, pady=4, cursor="hand2")
        del_btn.pack()
        del_btn.bind("<Button-1>",
            lambda e, zp=a["zip_path"], ttl=a["title"]: self._remove(zp, ttl))
        del_btn.bind("<Enter>", lambda e: del_btn.config(bg="#5a2020"))
        del_btn.bind("<Leave>", lambda e: del_btn.config(bg="#3a1515"))

    def _restore(self, zip_path: str, filename: str, source: str):
        source_label = "On Hold" if source == "onhold" else "Active"
        if not messagebox.askyesno(
            "Restore Task",
            f"Restore task to the {source_label} list?\n\n{filename}",
            parent=self.window
        ):
            return
        try:
            new_id = import_task_from_zip(zip_path)
            try:
                os.remove(zip_path)
            except Exception:
                pass
            if self.on_restore:
                self.on_restore()
            self._load()
            messagebox.showinfo("Task Restored",
                                f"Task has been restored (id={new_id}).",
                                parent=self.window)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to restore task:\n{e}",
                                 parent=self.window)

    def _remove(self, zip_path: str, title: str):
        if not messagebox.askyesno(
            "Delete from Archive",
            f"Delete task from archive?\n\n\"{title}\"\n\n"
            f"The ZIP file will be moved to the 'archive/removed' folder.\n"
            f"You can manually recover it from there.",
            parent=self.window
        ):
            return
        try:
            remove_archived_task(zip_path)
            self._load()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete task:\n{e}",
                                 parent=self.window)


# ---------------------------------------------------------------------------
# Run Application
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    root = tk.Tk()
    app = MainWindow(root)
    root.mainloop()
