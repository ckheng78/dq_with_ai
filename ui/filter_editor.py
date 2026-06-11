import tkinter as tk
from tkinter import ttk, messagebox

_STRING_OPS = ["contains", "not contains", "select", "not select"]
_DATE_OPS   = ["earlier than", "later than", "between"]

_OP_KEY = {
    "contains":     "contains",
    "not contains": "not_contains",
    "select":       "select",
    "not select":   "not_select",
    "earlier than": "earlier_than",
    "later than":   "later_than",
    "between":      "between",
}
_KEY_OP = {v: k for k, v in _OP_KEY.items()}


class FilterRow:
    """One filter row for a single field."""

    def __init__(self, parent, field_name: str, field_type: str, table_name: str):
        self.field_name = field_name
        self.field_type = field_type
        self.table_name = table_name

        self.frame = ttk.Frame(parent)

        self._enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.frame, variable=self._enabled_var,
                        command=self._on_toggle).grid(row=0, column=0, padx=(2, 0))

        ttk.Label(self.frame, text=field_name, width=36, anchor=tk.W,
                  font=("Courier", 9)).grid(row=0, column=1, padx=(4, 8), sticky=tk.W)

        ops = _DATE_OPS if field_type == "date" else _STRING_OPS
        self._op_var = tk.StringVar(value=ops[0])
        self._op_cb = ttk.Combobox(self.frame, textvariable=self._op_var,
                                   values=ops, state="disabled", width=13)
        self._op_cb.grid(row=0, column=2, padx=4)
        self._op_var.trace_add("write", lambda *_: self._rebuild_value())

        self._val_frame = ttk.Frame(self.frame)
        self._val_frame.grid(row=0, column=3, padx=4, sticky=tk.W)

        self._val1 = tk.StringVar()
        self._val2 = tk.StringVar()
        self._rebuild_value()

    def _on_toggle(self):
        enabled = self._enabled_var.get()
        self._op_cb.config(state="readonly" if enabled else "disabled")
        self._set_val_state("normal" if enabled else "disabled")

    def _set_val_state(self, state: str):
        for child in self._val_frame.winfo_children():
            try:
                child.config(state=state)
            except tk.TclError:
                pass

    def _rebuild_value(self):
        for w in self._val_frame.winfo_children():
            w.destroy()
        op = self._op_var.get()
        st = "normal" if self._enabled_var.get() else "disabled"

        if op in ("contains", "not contains"):
            ttk.Entry(self._val_frame, textvariable=self._val1,
                      width=28, state=st).pack(side=tk.LEFT)
            ttk.Label(self._val_frame, text="  (* = any chars,  ? = one char)",
                      foreground="gray").pack(side=tk.LEFT)
        elif op in ("select", "not select"):
            ttk.Entry(self._val_frame, textvariable=self._val1,
                      width=38, state=st).pack(side=tk.LEFT)
            ttk.Label(self._val_frame, text="  (comma-separated)",
                      foreground="gray").pack(side=tk.LEFT)
        elif op in ("earlier than", "later than"):
            ttk.Entry(self._val_frame, textvariable=self._val1,
                      width=13, state=st).pack(side=tk.LEFT)
            ttk.Label(self._val_frame, text="  YYYY-MM-DD",
                      foreground="gray").pack(side=tk.LEFT)
        elif op == "between":
            ttk.Entry(self._val_frame, textvariable=self._val1,
                      width=13, state=st).pack(side=tk.LEFT)
            ttk.Label(self._val_frame, text=" to ").pack(side=tk.LEFT)
            ttk.Entry(self._val_frame, textvariable=self._val2,
                      width=13, state=st).pack(side=tk.LEFT)
            ttk.Label(self._val_frame, text="  YYYY-MM-DD",
                      foreground="gray").pack(side=tk.LEFT)

    def get_filter(self) -> dict | None:
        if not self._enabled_var.get():
            return None
        return {
            "field":    self.field_name,
            "table":    self.table_name,
            "operator": _OP_KEY[self._op_var.get()],
            "value":    self._val1.get().strip(),
            "value2":   self._val2.get().strip(),
        }


class FilterEditorFrame(ttk.Frame):
    def __init__(self, parent, db, on_filters_applied, **kwargs):
        super().__init__(parent, **kwargs)
        self.db = db
        self.on_filters_applied = on_filters_applied
        self._filter_rows: list[FilterRow] = []

        # Top bar
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=8)
        ttk.Label(top, text="Optional per-field filters applied to each table before joining.").pack(
            side=tk.LEFT)
        self._next_btn = ttk.Button(top, text="Next: Define Join →",
                                    command=self._apply_and_proceed, state=tk.DISABLED)
        self._next_btn.pack(side=tk.RIGHT)

        # Column headers
        hdr = ttk.Frame(self)
        hdr.pack(fill=tk.X, padx=12, pady=(2, 0))
        ttk.Label(hdr, text="On",     width=4,  font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0)
        ttk.Label(hdr, text="Field",  width=36, font=("TkDefaultFont", 9, "bold"),
                  anchor=tk.W).grid(row=0, column=1, padx=(4, 8), sticky=tk.W)
        ttk.Label(hdr, text="Operator", width=13, font=("TkDefaultFont", 9, "bold"),
                  anchor=tk.W).grid(row=0, column=2, padx=4, sticky=tk.W)
        ttk.Label(hdr, text="Value",  font=("TkDefaultFont", 9, "bold"),
                  anchor=tk.W).grid(row=0, column=3, padx=4, sticky=tk.W)
        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=(2, 0))

        # Scrollable rows area
        outer = ttk.Frame(self)
        outer.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        vsb = ttk.Scrollbar(outer, orient=tk.VERTICAL)
        self._canvas = tk.Canvas(outer, highlightthickness=0, yscrollcommand=vsb.set)
        vsb.config(command=self._canvas.yview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._rows_frame = ttk.Frame(self._canvas)
        self._cw = self._canvas.create_window((0, 0), window=self._rows_frame, anchor="nw")
        self._rows_frame.bind("<Configure>",
                              lambda e: self._canvas.configure(
                                  scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfig(self._cw, width=e.width))
        self._canvas.bind("<Enter>",
                          lambda e: self._canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self._canvas.bind("<Leave>",
                          lambda e: self._canvas.unbind_all("<MouseWheel>"))

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def set_tables(self, table_names: list[str]):
        for row in self._filter_rows:
            row.frame.destroy()
        for w in self._rows_frame.winfo_children():
            w.destroy()
        self._filter_rows.clear()

        for table in table_names:
            ttk.Label(self._rows_frame, text=f"  {table}",
                      font=("TkDefaultFont", 9, "bold"), foreground="#444").pack(
                          fill=tk.X, pady=(8, 1), padx=4)
            col_types = self.db.get_column_types(table)
            for field, ftype in col_types.items():
                row = FilterRow(self._rows_frame, field, ftype, table)
                row.frame.pack(fill=tk.X, padx=4, pady=1)
                self._filter_rows.append(row)

        self._next_btn.config(state=tk.NORMAL)

    def load_filters(self, filters: list[dict]):
        """Pre-populate filter rows from a saved filter list."""
        filter_map = {f["field"]: f for f in filters}
        for row in self._filter_rows:
            if row.field_name not in filter_map:
                continue
            f = filter_map[row.field_name]
            row._enabled_var.set(True)
            row._on_toggle()
            op_display = _KEY_OP.get(f["operator"], f["operator"])
            row._op_var.set(op_display)
            row._val1.set(f.get("value", ""))
            row._val2.set(f.get("value2", ""))

    def _apply_and_proceed(self):
        filters = [f for row in self._filter_rows if (f := row.get_filter()) is not None]
        try:
            self.db.apply_filters(filters)
        except Exception as exc:
            messagebox.showerror("Filter Error", str(exc))
            return
        print(f"[FILTER] {len(filters)} active filter(s) applied")
        self.on_filters_applied(filters)


class PostJoinFilterFrame(ttk.Frame):
    """Per-field filters applied to joined_table before running rules."""

    def __init__(self, parent, db, on_filters_applied, **kwargs):
        super().__init__(parent, **kwargs)
        self.db = db
        self.on_filters_applied = on_filters_applied
        self._filter_rows: list[FilterRow] = []

        # Top bar
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=8)
        ttk.Label(top, text="Optional filters applied to the joined table before running rules.").pack(
            side=tk.LEFT)
        self._next_btn = ttk.Button(top, text="Next: Derived Fields →",
                                    command=self._apply_and_proceed, state=tk.DISABLED)
        self._next_btn.pack(side=tk.RIGHT)

        # Column headers
        hdr = ttk.Frame(self)
        hdr.pack(fill=tk.X, padx=12, pady=(2, 0))
        ttk.Label(hdr, text="On",     width=4,  font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0)
        ttk.Label(hdr, text="Field",  width=36, font=("TkDefaultFont", 9, "bold"),
                  anchor=tk.W).grid(row=0, column=1, padx=(4, 8), sticky=tk.W)
        ttk.Label(hdr, text="Operator", width=13, font=("TkDefaultFont", 9, "bold"),
                  anchor=tk.W).grid(row=0, column=2, padx=4, sticky=tk.W)
        ttk.Label(hdr, text="Value",  font=("TkDefaultFont", 9, "bold"),
                  anchor=tk.W).grid(row=0, column=3, padx=4, sticky=tk.W)
        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=(2, 0))

        # Scrollable rows area
        outer = ttk.Frame(self)
        outer.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        vsb = ttk.Scrollbar(outer, orient=tk.VERTICAL)
        self._canvas = tk.Canvas(outer, highlightthickness=0, yscrollcommand=vsb.set)
        vsb.config(command=self._canvas.yview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._rows_frame = ttk.Frame(self._canvas)
        self._cw = self._canvas.create_window((0, 0), window=self._rows_frame, anchor="nw")
        self._rows_frame.bind("<Configure>",
                              lambda e: self._canvas.configure(
                                  scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfig(self._cw, width=e.width))
        self._canvas.bind("<Enter>",
                          lambda e: self._canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self._canvas.bind("<Leave>",
                          lambda e: self._canvas.unbind_all("<MouseWheel>"))

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def set_joined_table(self, table_names: list[str]):
        """Populate filter rows from joined_table columns, grouped by original table prefix."""
        for row in self._filter_rows:
            row.frame.destroy()
        for w in self._rows_frame.winfo_children():
            w.destroy()
        self._filter_rows.clear()

        col_types = self.db.get_column_types("joined_table")

        for table in table_names:
            prefix = f"{table}_"
            table_cols = {col: t for col, t in col_types.items() if col.startswith(prefix)}
            if not table_cols:
                continue
            ttk.Label(self._rows_frame, text=f"  {table}",
                      font=("TkDefaultFont", 9, "bold"), foreground="#444").pack(
                          fill=tk.X, pady=(8, 1), padx=4)
            for field, ftype in table_cols.items():
                row = FilterRow(self._rows_frame, field, ftype, "joined_table")
                row.frame.pack(fill=tk.X, padx=4, pady=1)
                self._filter_rows.append(row)

        self._next_btn.config(state=tk.NORMAL)

    def load_filters(self, filters: list[dict]):
        """Pre-populate filter rows from a saved filter list."""
        filter_map = {f["field"]: f for f in filters}
        for row in self._filter_rows:
            if row.field_name not in filter_map:
                continue
            f = filter_map[row.field_name]
            row._enabled_var.set(True)
            row._on_toggle()
            op_display = _KEY_OP.get(f["operator"], f["operator"])
            row._op_var.set(op_display)
            row._val1.set(f.get("value", ""))
            row._val2.set(f.get("value2", ""))

    def _apply_and_proceed(self):
        filters = [f for row in self._filter_rows if (f := row.get_filter()) is not None]
        try:
            self.db.apply_join_filters(filters)
        except Exception as exc:
            messagebox.showerror("Filter Error", str(exc))
            return
        print(f"[POST-JOIN FILTER] {len(filters)} active filter(s) applied")
        self.on_filters_applied(filters)
