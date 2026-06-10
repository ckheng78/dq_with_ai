import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog


class RuleEditorFrame(ttk.Frame):
    def __init__(self, parent, db, llm, on_rules_run, **kwargs):
        super().__init__(parent, **kwargs)
        self.db = db
        self.llm = llm
        self.on_rules_run = on_rules_run
        self._rules = []  # list of {name, nl_description, sql}
        self._all_fields: list[str] = []

        left = ttk.LabelFrame(self, text="Rules")
        left.pack(side=tk.LEFT, fill=tk.BOTH, padx=(10, 4), pady=10, expand=False)
        left.config(width=220)

        self._rule_list = tk.Listbox(left, width=26, selectmode=tk.SINGLE, exportselection=False)
        self._rule_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._rule_list.bind("<<ListboxSelect>>", self._on_select)

        btn_col = ttk.Frame(left)
        btn_col.pack(fill=tk.X, padx=4, pady=(0, 4))
        ttk.Button(btn_col, text="+ Add Rule", command=self._add_rule).pack(side=tk.LEFT)
        ttk.Button(btn_col, text="Remove", command=self._remove_rule).pack(side=tk.LEFT, padx=4)

        right = ttk.Frame(self)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 10), pady=10)

        top_bar = ttk.Frame(right)
        top_bar.pack(fill=tk.X, pady=(0, 4))
        self._next_btn = ttk.Button(top_bar, text="Next: Reports →",
                                     command=self._proceed, state=tk.DISABLED)
        self._next_btn.pack(side=tk.RIGHT)

        ttk.Label(right, text="Rule description (plain English):").pack(anchor=tk.W)
        self._nl_input = tk.Text(right, height=3, wrap=tk.WORD, state=tk.DISABLED)
        self._nl_input.pack(fill=tk.X)

        btn_row = ttk.Frame(right)
        btn_row.pack(fill=tk.X, pady=4)
        self._translate_btn = ttk.Button(btn_row, text="Translate to SQL", command=self._translate, state=tk.DISABLED)
        self._translate_btn.pack(side=tk.LEFT)
        self._regen_btn = ttk.Button(btn_row, text="Regenerate", command=self._translate, state=tk.DISABLED)
        self._regen_btn.pack(side=tk.LEFT, padx=6)
        self._progress = ttk.Progressbar(btn_row, mode="indeterminate", length=100)
        self._progress.pack(side=tk.LEFT, padx=4)

        fields_lf = ttk.LabelFrame(right, text="Available fields (joined_table)")
        fields_lf.pack(fill=tk.X, pady=(4, 0))

        filter_row = ttk.Frame(fields_lf)
        filter_row.pack(fill=tk.X, padx=4, pady=(4, 0))
        ttk.Label(filter_row, text="Filter by table:").pack(side=tk.LEFT)
        self._table_filter_var = tk.StringVar(value="All tables")
        self._table_filter_cb = ttk.Combobox(filter_row, textvariable=self._table_filter_var,
                                              state="readonly", width=20)
        self._table_filter_cb["values"] = ["All tables"]
        self._table_filter_cb.pack(side=tk.LEFT, padx=6)
        self._table_filter_var.trace_add("write", lambda *_: self._apply_field_filter())

        field_frame = ttk.Frame(fields_lf)
        field_frame.pack(fill=tk.BOTH, expand=True)
        self._field_list = tk.Listbox(field_frame, height=5, selectmode=tk.SINGLE,
                                       exportselection=False, font=("Courier", 11))
        fields_vsb = ttk.Scrollbar(field_frame, orient=tk.VERTICAL, command=self._field_list.yview)
        self._field_list.configure(yscrollcommand=fields_vsb.set)
        self._field_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=4)
        fields_vsb.pack(side=tk.RIGHT, fill=tk.Y, pady=4, padx=(0, 4))

        ttk.Label(right, text="Generated SQL (review before running):").pack(anchor=tk.W, pady=(4, 2))
        self._sql_box = tk.Text(right, height=4, wrap=tk.WORD, state=tk.DISABLED, background="#f0f0f0")
        self._sql_box.pack(fill=tk.X)

        self._save_rule_btn = ttk.Button(right, text="Save SQL to Rule", command=self._save_sql_to_rule, state=tk.DISABLED)
        self._save_rule_btn.pack(anchor=tk.W, pady=4)

        action_row = ttk.Frame(right)
        action_row.pack(fill=tk.X, pady=(10, 0))
        self._run_btn = ttk.Button(action_row, text="Run All Rules", command=self._run_all, state=tk.DISABLED)
        self._run_btn.pack(side=tk.LEFT)
        self._run_progress = ttk.Progressbar(action_row, mode="indeterminate", length=120)
        self._run_progress.pack(side=tk.LEFT, padx=8)

    def set_fields(self, columns: list[str], table_names: list[str] = None):
        self._all_fields = list(columns)
        choices = ["All tables"] + (table_names or [])
        self._table_filter_cb["values"] = choices
        self._table_filter_var.set("All tables")
        self._apply_field_filter()

    def _apply_field_filter(self):
        sel = self._table_filter_var.get()
        self._field_list.delete(0, tk.END)
        for col in self._all_fields:
            if sel == "All tables" or col.startswith(sel + "_"):
                self._field_list.insert(tk.END, col)

    def load_rules(self, rules: list[dict]):
        self._rules = [dict(r) for r in rules]
        self._rule_list.delete(0, tk.END)
        for r in self._rules:
            self._rule_list.insert(tk.END, r["name"])
        self._update_run_btn()

    def _add_rule(self):
        name = simpledialog.askstring("New Rule", "Enter a short name for this rule (no spaces):")
        if not name:
            return
        safe_name = "".join(c if c.isalnum() else "_" for c in name.strip())
        for r in self._rules:
            if r["name"] == safe_name:
                messagebox.showwarning("Duplicate", f"A rule named '{safe_name}' already exists.")
                return
        self._rules.append({"name": safe_name, "nl_description": "", "sql": ""})
        self._rule_list.insert(tk.END, safe_name)
        self._rule_list.selection_clear(0, tk.END)
        self._rule_list.selection_set(tk.END)
        self._on_select(None)

    def _remove_rule(self):
        sel = self._rule_list.curselection()
        if not sel:
            return
        idx = sel[0]
        self._rules.pop(idx)
        self._rule_list.delete(idx)
        self._clear_editor()
        self._update_run_btn()

    def _on_select(self, _event):
        sel = self._rule_list.curselection()
        if not sel:
            return
        idx = sel[0]
        rule = self._rules[idx]
        for widget in (self._nl_input, self._sql_box):
            widget.config(state=tk.NORMAL)
        self._nl_input.delete("1.0", tk.END)
        self._nl_input.insert("1.0", rule.get("nl_description", ""))
        self._sql_box.delete("1.0", tk.END)
        self._sql_box.insert("1.0", rule.get("sql", ""))
        self._sql_box.config(state=tk.DISABLED)
        self._translate_btn.config(state=tk.NORMAL)
        self._regen_btn.config(state=tk.NORMAL)
        self._save_rule_btn.config(state=tk.NORMAL if rule.get("sql") else tk.DISABLED)

    def _clear_editor(self):
        for widget in (self._nl_input, self._sql_box):
            widget.config(state=tk.NORMAL)
            widget.delete("1.0", tk.END)
            widget.config(state=tk.DISABLED)
        self._translate_btn.config(state=tk.DISABLED)
        self._regen_btn.config(state=tk.DISABLED)
        self._save_rule_btn.config(state=tk.DISABLED)

    def _translate(self):
        sel = self._rule_list.curselection()
        if not sel:
            return
        nl = self._nl_input.get("1.0", tk.END).strip()
        if not nl:
            messagebox.showwarning("Input Required", "Please describe the rule in plain English first.")
            return

        idx = sel[0]
        self._rules[idx]["nl_description"] = nl
        self._progress.start(10)
        self._translate_btn.config(state=tk.DISABLED)

        def worker():
            try:
                col_hints = self.db.get_columns("joined_table")
                sql = self.llm.translate_rule(nl, col_hints)
                self.after(0, lambda: self._show_sql(sql))
            except Exception as exc:
                self.after(0, lambda e=exc: self._on_error(str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _show_sql(self, sql: str):
        self._progress.stop()
        self._sql_box.config(state=tk.NORMAL)
        self._sql_box.delete("1.0", tk.END)
        self._sql_box.insert("1.0", sql)
        self._sql_box.config(state=tk.DISABLED)
        self._translate_btn.config(state=tk.NORMAL)
        self._save_rule_btn.config(state=tk.NORMAL)

    def _on_error(self, msg: str):
        self._progress.stop()
        self._run_progress.stop()
        self._translate_btn.config(state=tk.NORMAL)
        messagebox.showerror("Error", msg)

    def _save_sql_to_rule(self):
        sel = self._rule_list.curselection()
        if not sel:
            return
        idx = sel[0]
        nl = self._nl_input.get("1.0", tk.END).strip()
        sql = self._sql_box.get("1.0", tk.END).strip()
        self._rules[idx]["nl_description"] = nl
        self._rules[idx]["sql"] = sql
        self._update_run_btn()
        messagebox.showinfo("Saved", f"Rule '{self._rules[idx]['name']}' updated.")

    def _update_run_btn(self):
        ready = any(r.get("sql") for r in self._rules)
        self._run_btn.config(state=tk.NORMAL if ready else tk.DISABLED)

    def _run_all(self):
        runnable = [r for r in self._rules if r.get("sql")]
        if not runnable:
            messagebox.showinfo("No Rules", "No rules with SQL to run.")
            return
        self._run_progress.start(10)
        self._run_btn.config(state=tk.DISABLED)

        def worker():
            from core.rules import run_all_rules
            try:
                results = run_all_rules(runnable, self.db)
                self.after(0, lambda: self._on_results(results))
            except Exception as exc:
                self.after(0, lambda e=exc: self._on_error(f"Rule execution failed:\n{e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_results(self, results):
        self._run_progress.stop()
        self._run_btn.config(state=tk.NORMAL)
        self._next_btn.config(state=tk.NORMAL)
        self.on_rules_run(results, self.get_rules())

    def get_rules(self) -> list[dict]:
        return [dict(r) for r in self._rules]

    def _proceed(self):
        self._run_all()
