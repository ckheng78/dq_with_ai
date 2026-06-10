import threading
import tkinter as tk
from tkinter import ttk, messagebox

OPERATORS = ["=", "!=", "<", ">", "<=", ">="]
BOOL_OPS = ["AND", "OR"]


class ConditionRow:
    """One condition row: [AND/OR?] [left_col] [operator] [right_col] [×]"""

    def __init__(self, parent, left_cols, right_cols, is_first, on_remove):
        self.frame = ttk.Frame(parent)
        self._is_first = is_first

        self.bool_var = tk.StringVar(value="AND")
        self.left_var = tk.StringVar(value=left_cols[0] if left_cols else "")
        self.op_var = tk.StringVar(value="=")
        self.right_var = tk.StringVar(value=right_cols[0] if right_cols else "")

        left_width = min(max((len(s) for s in left_cols), default=20) + 2, 60)
        right_width = min(max((len(s) for s in right_cols), default=20) + 2, 60)

        if is_first:
            ttk.Label(self.frame, width=7).grid(row=0, column=0)
        else:
            ttk.Combobox(self.frame, textvariable=self.bool_var, values=BOOL_OPS,
                         state="readonly", width=5).grid(row=0, column=0, padx=(0, 4))

        ttk.Combobox(self.frame, textvariable=self.left_var, values=left_cols,
                     state="readonly", width=left_width).grid(row=0, column=1, padx=2)
        ttk.Combobox(self.frame, textvariable=self.op_var, values=OPERATORS,
                     state="readonly", width=4).grid(row=0, column=2, padx=2)
        ttk.Combobox(self.frame, textvariable=self.right_var, values=right_cols,
                     state="readonly", width=right_width).grid(row=0, column=3, padx=2)
        ttk.Button(self.frame, text="×", width=2,
                   command=on_remove).grid(row=0, column=4, padx=(4, 0))

    def get(self):
        """Returns (bool_op_or_None, left_col, operator, right_col)."""
        bool_op = None if self._is_first else self.bool_var.get()
        return (bool_op, self.left_var.get(), self.op_var.get(), self.right_var.get())


class JoinRuleWidget:
    """Join rule panel for one secondary table: condition rows + Add Condition button."""

    def __init__(self, parent, rule_num, left_label, secondary, left_cols, right_cols):
        self.secondary = secondary
        self._left_cols = left_cols
        self._right_cols = right_cols
        self._conditions: list[ConditionRow] = []

        self.frame = ttk.LabelFrame(
            parent,
            text=f"Rule {rule_num}:  {left_label}  LEFT JOIN  {secondary}",
        )
        self._cond_frame = ttk.Frame(self.frame)
        self._cond_frame.pack(fill=tk.X, padx=6, pady=4)
        ttk.Button(self.frame, text="+ Add Condition",
                   command=self._add_condition).pack(anchor=tk.W, padx=6, pady=(0, 6))

        self._add_condition()

    def _add_condition(self, bool_op="AND", left="", op="=", right=""):
        is_first = len(self._conditions) == 0
        ref = [None]

        def on_remove():
            self._remove(ref[0])

        cond = ConditionRow(
            self._cond_frame, self._left_cols, self._right_cols, is_first, on_remove
        )
        ref[0] = cond

        if not is_first and bool_op:
            cond.bool_var.set(bool_op)
        if left:
            cond.left_var.set(left)
        if op:
            cond.op_var.set(op)
        if right:
            cond.right_var.set(right)

        cond.frame.pack(fill=tk.X, pady=2)
        self._conditions.append(cond)

    def _remove(self, cond):
        if len(self._conditions) <= 1:
            return
        idx = self._conditions.index(cond)
        self._conditions.remove(cond)
        cond.frame.destroy()
        if idx == 0:
            self._full_rebuild()

    def _full_rebuild(self):
        saved = [c.get() for c in self._conditions]
        for c in self._conditions:
            c.frame.destroy()
        self._conditions.clear()
        for bool_op, left, op, right in saved:
            self._add_condition(bool_op or "AND", left, op, right)

    def get_conditions(self):
        return [c.get() for c in self._conditions]

    def is_valid(self):
        return bool(self._conditions) and all(
            c.left_var.get() and c.right_var.get() for c in self._conditions
        )


class JoinEditorFrame(ttk.Frame):
    def __init__(self, parent, db, on_joined, **kwargs):
        super().__init__(parent, **kwargs)
        self.db = db
        self.on_joined = on_joined
        self._table_names: list[str] = []
        self._rule_widgets: list[JoinRuleWidget] = []

        # Master table selector
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=8)
        ttk.Label(top, text="Master table:").pack(side=tk.LEFT)
        self._master_var = tk.StringVar()
        self._master_cb = ttk.Combobox(top, textvariable=self._master_var,
                                        state="readonly", width=30)
        self._master_cb.pack(side=tk.LEFT, padx=6)
        self._master_var.trace_add("write", lambda *_: self._rebuild_rules())
        self._next_btn = ttk.Button(top, text="Next: Post-Join Filters →",
                                     command=self._proceed, state=tk.DISABLED)
        self._next_btn.pack(side=tk.RIGHT)

        # Join rules area — canvas provides horizontal scroll when conditions exceed window width
        rules_outer = ttk.Frame(self)
        rules_outer.pack(fill=tk.X, padx=10, pady=(0, 4))
        self._rules_canvas = tk.Canvas(rules_outer, highlightthickness=0)
        rules_hscroll = ttk.Scrollbar(rules_outer, orient=tk.HORIZONTAL,
                                       command=self._rules_canvas.xview)
        self._rules_canvas.configure(xscrollcommand=rules_hscroll.set)
        self._rules_frame = ttk.Frame(self._rules_canvas)
        self._rules_canvas.create_window((0, 0), window=self._rules_frame, anchor="nw")
        self._rules_frame.bind("<Configure>", self._on_rules_configure)
        rules_hscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self._rules_canvas.pack(side=tk.TOP, fill=tk.X)

        # Execute + progress
        mid = ttk.Frame(self)
        mid.pack(fill=tk.X, padx=10, pady=4)
        self._exec_btn = ttk.Button(mid, text="Execute Join & Preview",
                                     command=self._execute_join, state=tk.DISABLED)
        self._exec_btn.pack(side=tk.LEFT)
        self._progress = ttk.Progressbar(mid, mode="indeterminate", length=120)
        self._progress.pack(side=tk.LEFT, padx=8)

        # Preview treeview
        ttk.Label(self, text="Preview of joined table (first 100 rows):").pack(
            anchor=tk.W, padx=10, pady=(4, 2))
        pf = ttk.Frame(self)
        pf.pack(fill=tk.BOTH, expand=True, padx=10)
        self._tree = ttk.Treeview(pf, show="headings", height=10)
        vsb = ttk.Scrollbar(pf, orient=tk.VERTICAL, command=self._tree.yview)
        hsb = ttk.Scrollbar(pf, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        pf.rowconfigure(0, weight=1)
        pf.columnconfigure(0, weight=1)

    def _on_rules_configure(self, event=None):
        self._rules_canvas.configure(scrollregion=self._rules_canvas.bbox("all"))
        h = self._rules_frame.winfo_reqheight()
        if h > 0:
            self._rules_canvas.configure(height=h)

    def set_tables(self, table_names: list[str]):
        self._table_names = table_names
        self._master_cb["values"] = table_names
        if table_names:
            self._master_var.set(table_names[0])

    def _rebuild_rules(self):
        for w in self._rule_widgets:
            w.frame.destroy()
        self._rule_widgets.clear()

        master = self._master_var.get()
        if not master or master not in self._table_names:
            self._exec_btn.config(state=tk.DISABLED)
            return

        secondaries = [t for t in self._table_names if t != master]
        if not secondaries:
            self._exec_btn.config(state=tk.DISABLED)
            return

        accumulated_cols = list(self.db.get_columns(master))
        left_label = master

        for i, secondary in enumerate(secondaries):
            right_cols = list(self.db.get_columns(secondary))
            widget = JoinRuleWidget(
                self._rules_frame,
                rule_num=i + 1,
                left_label=left_label,
                secondary=secondary,
                left_cols=list(accumulated_cols),
                right_cols=right_cols,
            )
            widget.frame.pack(fill=tk.X, pady=4)
            self._rule_widgets.append(widget)
            accumulated_cols.extend(right_cols)
            left_label = f"{left_label}+{secondary}"

        self._exec_btn.config(state=tk.NORMAL)

    def _build_sql(self) -> str | None:
        master = self._master_var.get()
        if not master:
            return None
        lines = [f'SELECT * FROM "{master}"']
        for widget in self._rule_widgets:
            if not widget.is_valid():
                return None
            on_parts = []
            for i, (bool_op, left, op, right) in enumerate(widget.get_conditions()):
                expr = f'"{left}" {op} "{right}"'
                on_parts.append(expr if i == 0 else f"{bool_op} {expr}")
            lines.append(f'LEFT JOIN "{widget.secondary}" ON {" ".join(on_parts)}')
        return "\n".join(lines)

    def _execute_join(self):
        sql = self._build_sql()
        if not sql:
            messagebox.showwarning("Incomplete", "Please complete all join conditions.")
            return
        print(f"[JOIN] Generated SQL:\n{sql}")
        self._progress.start(10)
        self._exec_btn.config(state=tk.DISABLED)

        def worker():
            try:
                self.db.execute_join(sql)
                cols, rows = self.db.get_joined_preview()
                self.after(0, lambda: self._show_preview(cols, rows))
            except Exception as exc:
                self.after(0, lambda e=exc: self._on_error(f"Join failed:\n{e}\n\nSQL:\n{sql}"))

        threading.Thread(target=worker, daemon=True).start()

    def _show_preview(self, cols, rows):
        self._progress.stop()
        self._exec_btn.config(state=tk.NORMAL)
        self._tree.config(columns=cols)
        for col in cols:
            self._tree.heading(col, text=col)
            col_px = max(len(col) * 9, 80)
            self._tree.column(col, width=col_px, minwidth=col_px, stretch=False)
        for item in self._tree.get_children():
            self._tree.delete(item)
        for row in rows:
            self._tree.insert("", tk.END, values=[str(v) if v is not None else "" for v in row])
        self._next_btn.config(state=tk.NORMAL)

    def _on_error(self, msg):
        self._progress.stop()
        self._exec_btn.config(state=tk.NORMAL)
        messagebox.showerror("Join Error", msg)

    def get_join_config(self) -> dict:
        return {
            "tables": self._table_names,
            "master": self._master_var.get(),
            "sql": self._build_sql() or "",
        }

    def _proceed(self):
        self.on_joined(self.get_join_config())
