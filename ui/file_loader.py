import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

_ENCODINGS = ["utf-8", "latin-1", "cp1252", "utf-16", "ascii"]
_DELIMITERS = {"Comma (,)": ",", "Tab (\\t)": "\t", "Semicolon (;)": ";", "Pipe (|)": "|"}
_ENGINES = ["C", "Python"]
_DATE_FORMATS = ["Auto", "YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY", "DD/MM/YYYY HH:MM:SS", "MM/DD/YYYY HH:MM:SS", "DD-MM-YYYY"]


class FileOptionsDialog(tk.Toplevel):
    """Per-file load options: encoding, delimiter, engine, date format."""

    def __init__(self, parent, filename):
        super().__init__(parent)
        self.title(f"Load Options — {filename}")
        self.resizable(False, False)
        self.grab_set()
        self.result = None  # set to dict on OK, stays None on cancel

        ttk.Label(self, text=f"Options for:  {filename}",
                  font=("TkDefaultFont", 10, "bold")).pack(padx=14, pady=(12, 8))

        grid = ttk.Frame(self)
        grid.pack(padx=14, pady=4)

        ttk.Label(grid, text="Encoding:").grid(row=0, column=0, sticky=tk.W, pady=4)
        self._enc_var = tk.StringVar(value="utf-8")
        ttk.Combobox(grid, textvariable=self._enc_var, values=_ENCODINGS,
                     state="readonly", width=22).grid(row=0, column=1, padx=8)

        ttk.Label(grid, text="Delimiter:").grid(row=1, column=0, sticky=tk.W, pady=4)
        self._delim_var = tk.StringVar(value="Comma (,)")
        ttk.Combobox(grid, textvariable=self._delim_var, values=list(_DELIMITERS.keys()),
                     state="readonly", width=22).grid(row=1, column=1, padx=8)

        ttk.Label(grid, text="Engine:").grid(row=2, column=0, sticky=tk.W, pady=4)
        self._engine_var = tk.StringVar(value="C")
        ttk.Combobox(grid, textvariable=self._engine_var, values=_ENGINES,
                     state="readonly", width=22).grid(row=2, column=1, padx=8)

        ttk.Label(grid, text="Date format:").grid(row=3, column=0, sticky=tk.W, pady=4)
        self._datefmt_var = tk.StringVar(value="Auto")
        ttk.Combobox(grid, textvariable=self._datefmt_var, values=_DATE_FORMATS,
                     state="readonly", width=22).grid(row=3, column=1, padx=8)

        btn_row = ttk.Frame(self)
        btn_row.pack(pady=12)
        ttk.Button(btn_row, text="Load", command=self._ok).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side=tk.LEFT)

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_window()

    def _ok(self):
        self.result = {
            "encoding":    self._enc_var.get(),
            "delimiter":   _DELIMITERS[self._delim_var.get()],
            "engine":      self._engine_var.get(),
            "date_format": self._datefmt_var.get(),
        }
        self.destroy()


_COL_TYPES = ["VARCHAR"] + _DATE_FORMATS + ["NUMERIC", "CURRENCY"]


class FieldSelectorDialog(tk.Toplevel):
    """Column picker shown after file options are confirmed.

    result: list[str] of selected column names (on OK), None on cancel
    column_types: dict[str, str] mapping col name → lowercase type for selected cols
    """

    def __init__(self, parent, filename, columns, samples: dict,
                 detected_dates: set = None, default_date_format: str = "Auto"):
        super().__init__(parent)
        self.title(f"Select Fields — {filename}")
        self.resizable(True, True)
        self.grab_set()
        self.result = None
        self.column_types = {}
        self._columns = columns
        detected_dates = detected_dates or set()

        ttk.Label(self, text="Choose fields to load  (at least 1 required):",
                  font=("TkDefaultFont", 10, "bold")).pack(padx=14, pady=(12, 2))
        ttk.Label(self, text=f"{len(columns)} columns — set type per field; sample values shown for preview").pack(
            padx=14, anchor=tk.W)

        sel_row = ttk.Frame(self)
        sel_row.pack(fill=tk.X, padx=14, pady=(6, 2))
        ttk.Button(sel_row, text="Select All", command=self._select_all).pack(side=tk.LEFT)
        ttk.Button(sel_row, text="Clear All", command=self._clear_all).pack(side=tk.LEFT, padx=6)

        # Scrollable canvas for per-row widgets
        outer = ttk.Frame(self)
        outer.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 4))
        canvas = tk.Canvas(outer, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inner = ttk.Frame(canvas)
        canvas_win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(e):
            canvas.itemconfig(canvas_win, width=e.width)
        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        col_width = max((len(c) for c in columns), default=20)
        self._check_vars: list[tk.BooleanVar] = []
        self._type_vars: list[tk.StringVar] = []

        for col in columns:
            default_type = default_date_format if col in detected_dates else "VARCHAR"
            chk_var = tk.BooleanVar(value=True)
            type_var = tk.StringVar(value=default_type)
            self._check_vars.append(chk_var)
            self._type_vars.append(type_var)

            row_frame = ttk.Frame(inner)
            row_frame.pack(fill=tk.X, pady=1)
            ttk.Checkbutton(row_frame, variable=chk_var).pack(side=tk.LEFT)
            vals = samples.get(col, [])
            val_str = ",  ".join(f'"{v}"' for v in vals[:3]) if vals else "(no data)"
            ttk.Label(row_frame, text=f"{col:<{col_width}}    {val_str}",
                      font=("Courier", 10), anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True)
            ttk.Combobox(row_frame, textvariable=type_var, values=_COL_TYPES,
                         state="readonly", width=22).pack(side=tk.RIGHT, padx=(6, 0))

        # Bind mousewheel for scroll
        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.protocol("WM_DELETE_WINDOW", lambda: (canvas.unbind_all("<MouseWheel>"), self.destroy()))

        self._err_var = tk.StringVar()
        ttk.Label(self, textvariable=self._err_var, foreground="red").pack(padx=14, anchor=tk.W)

        btn_row = ttk.Frame(self)
        btn_row.pack(pady=(4, 12))
        ttk.Button(btn_row, text="Load", command=self._ok).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side=tk.LEFT)

        self.wait_window()

    def _select_all(self):
        for v in self._check_vars:
            v.set(True)
        self._err_var.set("")

    def _clear_all(self):
        for v in self._check_vars:
            v.set(False)

    def _ok(self):
        selected = [col for col, v in zip(self._columns, self._check_vars) if v.get()]
        if not selected:
            self._err_var.set("Please select at least one field.")
            return
        self.result = selected
        self.column_types = {
            col: type_var.get()
            for col, chk_var, type_var in zip(self._columns, self._check_vars, self._type_vars)
            if chk_var.get()
        }
        self.destroy()


class FileLoaderFrame(ttk.Frame):
    def __init__(self, parent, db, on_loaded, **kwargs):
        super().__init__(parent, **kwargs)
        self.db = db
        self.on_loaded = on_loaded
        self._loaded_files = {}  # name -> {path, encoding, delimiter, engine}

        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(top, text="Add CSV File(s)", command=self._pick_files).pack(side=tk.LEFT)
        ttk.Button(top, text="Remove Selected", command=self._remove_selected).pack(side=tk.LEFT, padx=6)
        self._next_btn = ttk.Button(top, text="Next: Pre-Join Filters →", command=self._proceed, state=tk.DISABLED)
        self._next_btn.pack(side=tk.RIGHT)

        list_frame = ttk.LabelFrame(self, text="Loaded Files")
        list_frame.pack(fill=tk.X, padx=10, pady=(0, 6))
        self._file_list = tk.Listbox(list_frame, height=4, selectmode=tk.SINGLE, exportselection=False)
        self._file_list.pack(fill=tk.X, padx=6, pady=6)

        self._preview_nb = ttk.Notebook(self)
        self._preview_nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

    def _pick_files(self):
        paths = filedialog.askopenfilenames(
            title="Select CSV Files",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        for path in paths:
            name = os.path.splitext(os.path.basename(path))[0]
            safe_name = "".join(c if c.isalnum() else "_" for c in name)
            if safe_name in self._loaded_files:
                messagebox.showwarning("Duplicate", f"A table named '{safe_name}' is already loaded.")
                continue

            dlg = FileOptionsDialog(self, os.path.basename(path))
            if dlg.result is None:
                continue  # user cancelled

            opts = dlg.result
            csv_opts = {k: opts[k] for k in ("encoding", "delimiter", "engine")}
            try:
                all_cols, samples = self.db.get_csv_sample_values(path, **csv_opts, n_rows=5000, n_distinct=16)
            except Exception as exc:
                messagebox.showerror("Read Error", f"Could not read columns from {os.path.basename(path)}:\n{exc}")
                continue

            detected_dates = set(self.db.detect_date_columns(path, date_format=opts["date_format"], **csv_opts))
            dlg2 = FieldSelectorDialog(self, os.path.basename(path), all_cols, samples,
                                       detected_dates=detected_dates,
                                       default_date_format=opts["date_format"])
            if dlg2.result is None:
                continue  # user cancelled field selection

            selected_cols = dlg2.result
            col_types = dlg2.column_types
            try:
                self.db.register_csv(safe_name, path, selected_columns=selected_cols,
                                     date_format=opts["date_format"], column_types=col_types,
                                     **csv_opts)
                # Build distinct-value hints for filter dropdowns (only cols with ≤15 distinct values
                # from the 5000-row sample; len==16 means "more than 15", so skip those).
                distinct_values = {
                    f"{safe_name}_{col}": sorted(vals)
                    for col, vals in samples.items()
                    if col in selected_cols and 0 < len(vals) <= 15
                }
                self._loaded_files[safe_name] = {"path": path, "selected_columns": selected_cols,
                                                 "column_types": col_types,
                                                 "distinct_values": distinct_values, **opts}
                delim_display = next(k for k, v in _DELIMITERS.items() if v == opts["delimiter"])
                fmt_tag = f", dfmt={opts['date_format']}" if opts["date_format"] != "Auto" else ""
                self._file_list.insert(
                    tk.END,
                    f"{safe_name}  [enc={opts['encoding']}, delim={delim_display}, "
                    f"engine={opts['engine']}, fields={len(selected_cols)}/{len(all_cols)}{fmt_tag}]"
                )
                self._add_preview_tab(safe_name)
            except Exception as exc:
                messagebox.showerror("Load Error", f"Failed to load {path}:\n{exc}")

        self._next_btn.config(state=tk.NORMAL if self._loaded_files else tk.DISABLED)

    def _remove_selected(self):
        sel = self._file_list.curselection()
        if not sel:
            return
        idx = sel[0]
        entry = self._file_list.get(idx)
        name = entry.split("  [")[0]
        self._file_list.delete(idx)
        self._loaded_files.pop(name, None)
        for tab_id in self._preview_nb.tabs():
            if self._preview_nb.tab(tab_id, "text") == name:
                self._preview_nb.forget(tab_id)
                break
        self._next_btn.config(state=tk.NORMAL if self._loaded_files else tk.DISABLED)

    def _add_preview_tab(self, table_name: str):
        frame = ttk.Frame(self._preview_nb)
        self._preview_nb.add(frame, text=table_name)
        try:
            cols, rows = self.db.get_preview(table_name)
        except Exception as exc:
            ttk.Label(frame, text=f"Preview error: {exc}").pack(padx=10, pady=10)
            return

        tree = ttk.Treeview(frame, columns=cols, show="headings", height=12)
        for col in cols:
            tree.heading(col, text=col)
            col_px = max(len(col) * 9, 80)
            tree.column(col, width=col_px, minwidth=col_px, stretch=False)
        for row in rows:
            tree.insert("", tk.END, values=[str(v) if v is not None else "" for v in row])

        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

    def get_file_configs(self, base_dir: str) -> list[dict]:
        result = []
        for name, cfg in self._loaded_files.items():
            result.append({
                "name": name,
                "path": os.path.relpath(cfg["path"], base_dir),
                "encoding": cfg["encoding"],
                "delimiter": cfg["delimiter"],
                "engine": cfg["engine"],
                "date_format": cfg.get("date_format", "Auto"),
                "selected_columns": cfg["selected_columns"],
                "column_types": cfg.get("column_types", {}),
            })
        return result

    def populate_from_workflow(self, file_configs: list[dict], base_dir: str):
        """Populate the UI from a saved workflow (CSVs already registered in db)."""
        for fc in file_configs:
            name = fc["name"]
            if name in self._loaded_files:
                continue
            abs_path = os.path.normpath(os.path.join(base_dir, fc["path"]))
            date_format = fc.get("date_format", "Auto")
            opts = {k: fc[k] for k in ("encoding", "delimiter", "engine")}
            self._loaded_files[name] = {"path": abs_path, "selected_columns": fc["selected_columns"],
                                        "date_format": date_format,
                                        "column_types": fc.get("column_types", {}), **opts}
            n = len(fc["selected_columns"])
            delim_display = next(k for k, v in _DELIMITERS.items() if v == opts["delimiter"])
            fmt_tag = f", dfmt={date_format}" if date_format != "Auto" else ""
            self._file_list.insert(
                tk.END,
                f"{name}  [enc={opts['encoding']}, delim={delim_display}, "
                f"engine={opts['engine']}, fields={n}/{n}{fmt_tag}]",
            )
            self._add_preview_tab(name)
        self._next_btn.config(state=tk.NORMAL if self._loaded_files else tk.DISABLED)

    def _proceed(self):
        if len(self._loaded_files) < 2:
            messagebox.showinfo("Two Tables Required", "Please load at least 2 CSV files to define a join.")
            return
        merged_distinct: dict = {}
        for cfg in self._loaded_files.values():
            merged_distinct.update(cfg.get("distinct_values", {}))
        self.on_loaded(list(self._loaded_files.keys()), merged_distinct)
