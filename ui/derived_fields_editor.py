import tkinter as tk
from tkinter import ttk, messagebox

_CATEGORIES = ["String", "Date", "Numeric", "Conditional", "Regex"]

_OPERATIONS = {
    "String":      ["Concatenate", "Upper", "Lower", "Length", "Substring"],
    "Date":        ["Extract Year", "Extract Month", "Extract Day", "Days between", "Months between", "Years between"],
    "Numeric":     ["Add", "Subtract", "Multiply", "Divide", "Round"],
    "Conditional": ["If / Then / Else"],
    "Regex":       ["Match", "Extract", "Replace"],
}


def _build_expression(op: str, inputs: dict) -> str | None:
    def qf(name: str) -> str:
        return f'"{name}"'

    def esc(v: str) -> str:
        return v.replace("'", "''")

    def num_op(v: str) -> str:
        try:
            float(v)
            return v
        except ValueError:
            return f'CAST({qf(v)} AS DOUBLE)'

    def date_ref(v: str) -> str:
        return "CURRENT_DATE" if v == "TODAY" else qf(v)

    try:
        if op == "Upper":
            return f"UPPER({qf(inputs['field'])})"
        if op == "Lower":
            return f"LOWER({qf(inputs['field'])})"
        if op == "Length":
            return f"LENGTH({qf(inputs['field'])})"
        if op == "Concatenate":
            sep = esc(inputs.get("sep", "_"))
            return f"CONCAT({qf(inputs['field1'])}, '{sep}', {qf(inputs['field2'])})"
        if op == "Substring":
            return f"SUBSTR({qf(inputs['field'])}, {int(inputs['start'])}, {int(inputs['length'])})"
        if op == "Extract Year":
            return f"YEAR({qf(inputs['field'])})"
        if op == "Extract Month":
            return f"MONTH({qf(inputs['field'])})"
        if op == "Extract Day":
            return f"DAY({qf(inputs['field'])})"
        if op in ("Days between", "Months between", "Years between"):
            unit = {"Days between": "day", "Months between": "month", "Years between": "year"}[op]
            return f"DATEDIFF('{unit}', {date_ref(inputs['field1'])}, {date_ref(inputs['field2'])})"
        if op == "Match":
            return f"CAST(regexp_matches({qf(inputs['field'])}, '{esc(inputs['pattern'])}') AS VARCHAR)"
        if op == "Extract":
            return f"regexp_extract({qf(inputs['field'])}, '{esc(inputs['pattern'])}')"
        if op == "Replace":
            return f"regexp_replace({qf(inputs['field'])}, '{esc(inputs['pattern'])}', '{esc(inputs['replacement'])}')"
        if op == "Add":
            return f"CAST({qf(inputs['field1'])} AS DOUBLE) + {num_op(inputs['operand2'])}"
        if op == "Subtract":
            return f"CAST({qf(inputs['field1'])} AS DOUBLE) - {num_op(inputs['operand2'])}"
        if op == "Multiply":
            return f"CAST({qf(inputs['field1'])} AS DOUBLE) * {num_op(inputs['operand2'])}"
        if op == "Divide":
            return f"CAST({qf(inputs['field1'])} AS DOUBLE) / NULLIF({num_op(inputs['operand2'])}, 0)"
        if op == "Round":
            return f"ROUND(CAST({qf(inputs['field'])} AS DOUBLE), {int(inputs['decimals'])})"
        if op == "If / Then / Else":
            cond_field = qf(inputs["field"])
            cond_op    = inputs["cond_op"]
            cond_val   = esc(inputs["cond_val"])
            then_val   = esc(inputs["then_val"])
            else_val   = esc(inputs["else_val"])
            return (f"CASE WHEN {cond_field} {cond_op} '{cond_val}' "
                    f"THEN '{then_val}' ELSE '{else_val}' END")
    except (KeyError, ValueError):
        return None
    return None


class DerivedFieldRow:
    """One row for a single derived field definition."""

    def __init__(self, parent, columns: list[str], row_num: int):
        self._columns = columns
        self._input_vars: dict[str, tk.StringVar] = {}

        self.frame = ttk.Frame(parent)

        self._enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.frame, variable=self._enabled,
                        command=self._on_toggle).grid(row=0, column=0, padx=(2, 0))

        ttk.Label(self.frame, text="Name:").grid(row=0, column=1, padx=(8, 2))
        self._name_var = tk.StringVar(value=f"derived_{row_num}")
        self._name_entry = ttk.Entry(self.frame, textvariable=self._name_var,
                                     width=16, state="disabled")
        self._name_entry.grid(row=0, column=2, padx=(0, 6))

        self._cat_var = tk.StringVar(value="String")
        self._cat_cb = ttk.Combobox(self.frame, textvariable=self._cat_var,
                                    values=_CATEGORIES, state="disabled", width=9)
        self._cat_cb.grid(row=0, column=3, padx=4)
        self._cat_var.trace_add("write", lambda *_: self._on_cat_change())

        self._op_var = tk.StringVar(value=_OPERATIONS["String"][0])
        self._op_cb = ttk.Combobox(self.frame, textvariable=self._op_var,
                                   values=_OPERATIONS["String"], state="disabled", width=13)
        self._op_cb.grid(row=0, column=4, padx=4)
        self._op_var.trace_add("write", lambda *_: self._rebuild_inputs())

        self._builder_frame = ttk.Frame(self.frame)
        self._builder_frame.grid(row=0, column=5, padx=4, sticky=tk.W)

        self._adv_var = tk.BooleanVar(value=False)
        self._adv_cb = ttk.Checkbutton(self.frame, text="Adv", variable=self._adv_var,
                                       command=self._on_adv_toggle, state="disabled")
        self._adv_cb.grid(row=0, column=6, padx=(8, 2))

        self._adv_entry_frame = ttk.Frame(self.frame)
        self._adv_expr_var = tk.StringVar()
        self._adv_entry = ttk.Entry(self._adv_entry_frame, textvariable=self._adv_expr_var,
                                    width=42, state="disabled")
        self._adv_entry.pack(side=tk.LEFT)
        ttk.Label(self._adv_entry_frame, text="  (DuckDB expression)",
                  foreground="gray").pack(side=tk.LEFT)

        self._rebuild_inputs()

    def _on_toggle(self):
        enabled = self._enabled.get()
        self._name_entry.config(state="normal" if enabled else "disabled")
        self._cat_cb.config(state="readonly" if enabled else "disabled")
        self._op_cb.config(state="readonly" if enabled else "disabled")
        self._adv_cb.config(state="normal" if enabled else "disabled")
        if self._adv_var.get():
            self._adv_entry.config(state="normal" if enabled else "disabled")
        else:
            self._set_states(self._builder_frame, "normal" if enabled else "disabled")

    def _set_states(self, frame, state: str):
        for child in frame.winfo_children():
            try:
                child.config(state=state)
            except tk.TclError:
                pass

    def _on_cat_change(self):
        cat = self._cat_var.get()
        ops = _OPERATIONS.get(cat, [])
        self._op_cb.config(values=ops)
        if ops:
            self._op_var.set(ops[0])

    def _on_adv_toggle(self):
        adv = self._adv_var.get()
        enabled = self._enabled.get()
        st = "normal" if enabled else "disabled"
        if adv:
            self._builder_frame.grid_remove()
            self._adv_entry_frame.grid(row=0, column=5, padx=4, sticky=tk.W)
            self._adv_entry.config(state=st)
        else:
            self._adv_entry_frame.grid_remove()
            self._builder_frame.grid(row=0, column=5, padx=4, sticky=tk.W)
            self._set_states(self._builder_frame, st)

    def _rebuild_inputs(self):
        for w in self._builder_frame.winfo_children():
            w.destroy()
        self._input_vars = {}
        op = self._op_var.get()
        enabled = self._enabled.get()
        st = "normal" if enabled else "disabled"
        ro = "readonly" if enabled else "disabled"
        cols = self._columns

        def field_cb(key: str, width: int = 26) -> tk.StringVar:
            v = tk.StringVar(value=cols[0] if cols else "")
            self._input_vars[key] = v
            ttk.Combobox(self._builder_frame, textvariable=v, values=cols,
                         state=ro, width=width).pack(side=tk.LEFT, padx=2)
            return v

        def date_cb(key: str, width: int = 22) -> tk.StringVar:
            date_vals = ["TODAY"] + cols
            v = tk.StringVar(value=cols[0] if cols else "TODAY")
            self._input_vars[key] = v
            ttk.Combobox(self._builder_frame, textvariable=v, values=date_vals,
                         state=ro, width=width).pack(side=tk.LEFT, padx=2)
            return v

        def entry(key: str, width: int = 8, default: str = "") -> tk.StringVar:
            v = tk.StringVar(value=default)
            self._input_vars[key] = v
            ttk.Entry(self._builder_frame, textvariable=v,
                      width=width, state=st).pack(side=tk.LEFT, padx=2)
            return v

        def lbl(text: str):
            ttk.Label(self._builder_frame, text=text,
                      foreground="gray").pack(side=tk.LEFT, padx=1)

        if op in ("Upper", "Lower", "Length", "Extract Year", "Extract Month", "Extract Day"):
            field_cb("field")

        elif op == "Concatenate":
            field_cb("field1", width=22)
            lbl("+")
            entry("sep", width=5, default="_")
            lbl("+")
            field_cb("field2", width=22)

        elif op == "Substring":
            field_cb("field", width=22)
            lbl("start:")
            entry("start", width=4, default="1")
            lbl("len:")
            entry("length", width=4, default="5")

        elif op in ("Days between", "Months between", "Years between"):
            date_cb("field1", width=22)
            lbl("to")
            date_cb("field2", width=22)

        elif op in ("Add", "Subtract", "Multiply", "Divide"):
            sym = {"Add": "+", "Subtract": "−", "Multiply": "×", "Divide": "÷"}[op]
            field_cb("field1", width=22)
            lbl(sym)
            v = tk.StringVar(value=cols[0] if cols else "0")
            self._input_vars["operand2"] = v
            ttk.Combobox(self._builder_frame, textvariable=v, values=cols,
                         state=st, width=18).pack(side=tk.LEFT, padx=2)
            lbl("(field or number)")

        elif op == "Round":
            field_cb("field", width=22)
            lbl("decimals:")
            entry("decimals", width=3, default="2")

        elif op == "Match":
            field_cb("field", width=22)
            lbl("matches:")
            entry("pattern", width=20)

        elif op == "Extract":
            field_cb("field", width=22)
            lbl("pattern:")
            entry("pattern", width=20)

        elif op == "Replace":
            field_cb("field", width=20)
            lbl("pattern:")
            entry("pattern", width=14)
            lbl("→")
            entry("replacement", width=14)

        elif op == "If / Then / Else":
            field_cb("field", width=18)
            cond_ops = ["=", "!=", ">", "<", ">=", "<="]
            v = tk.StringVar(value="=")
            self._input_vars["cond_op"] = v
            ttk.Combobox(self._builder_frame, textvariable=v,
                         values=cond_ops, state=ro, width=3).pack(side=tk.LEFT, padx=2)
            entry("cond_val", width=10)
            lbl("then:")
            entry("then_val", width=10)
            lbl("else:")
            entry("else_val", width=10)

    def get_derived(self) -> dict | None:
        if not self._enabled.get():
            return None
        name = self._name_var.get().strip()
        if not name:
            return None
        if self._adv_var.get():
            expr = self._adv_expr_var.get().strip()
            if not expr:
                return None
        else:
            inputs = {k: v.get() for k, v in self._input_vars.items()}
            expr = _build_expression(self._op_var.get(), inputs)
            if not expr:
                return None
        return {"name": name, "expression": expr}


class DerivedFieldsEditorFrame(ttk.Frame):
    def __init__(self, parent, db, on_applied, **kwargs):
        super().__init__(parent, **kwargs)
        self.db = db
        self.on_applied = on_applied
        self._rows: list[DerivedFieldRow] = []
        self._columns: list[str] = []
        self._row_count = 0

        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=8)
        ttk.Label(top, text="Optional: define new fields computed from existing columns.").pack(
            side=tk.LEFT)
        self._next_btn = ttk.Button(top, text="Next: Define Rules →",
                                    command=self._apply_and_proceed, state=tk.DISABLED)
        self._next_btn.pack(side=tk.RIGHT)

        hdr = ttk.Frame(self)
        hdr.pack(fill=tk.X, padx=12, pady=(2, 0))
        ttk.Label(hdr, text="On",        width=4,  font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0)
        ttk.Label(hdr, text="Name",      width=18, font=("TkDefaultFont", 9, "bold"),
                  anchor=tk.W).grid(row=0, column=1, padx=(4, 4), sticky=tk.W)
        ttk.Label(hdr, text="Category",  width=10, font=("TkDefaultFont", 9, "bold"),
                  anchor=tk.W).grid(row=0, column=2, padx=4, sticky=tk.W)
        ttk.Label(hdr, text="Operation", width=14, font=("TkDefaultFont", 9, "bold"),
                  anchor=tk.W).grid(row=0, column=3, padx=4, sticky=tk.W)
        ttk.Label(hdr, text="Inputs / Expression", font=("TkDefaultFont", 9, "bold"),
                  anchor=tk.W).grid(row=0, column=4, padx=4, sticky=tk.W)
        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=(2, 0))

        outer = ttk.Frame(self)
        outer.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 4))
        vsb = ttk.Scrollbar(outer, orient=tk.VERTICAL)
        self._canvas = tk.Canvas(outer, highlightthickness=0, yscrollcommand=vsb.set)
        vsb.config(command=self._canvas.yview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._rows_frame = ttk.Frame(self._canvas)
        self._cw = self._canvas.create_window((0, 0), window=self._rows_frame, anchor="nw")
        self._rows_frame.bind("<Configure>",
                              lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfig(self._cw, width=e.width))
        self._canvas.bind("<Enter>",
                          lambda e: self._canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self._canvas.bind("<Leave>",
                          lambda e: self._canvas.unbind_all("<MouseWheel>"))

        bot = ttk.Frame(self)
        bot.pack(fill=tk.X, padx=10, pady=(0, 8))
        self._add_btn = ttk.Button(bot, text="+ Add Field", command=self._add_row, state=tk.DISABLED)
        self._add_btn.pack(side=tk.LEFT)

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def set_columns(self, columns: list[str]):
        self._columns = list(columns)
        for row in self._rows:
            row.frame.destroy()
        self._rows.clear()
        self._row_count = 0
        for _ in range(3):
            self._add_row()
        self._next_btn.config(state=tk.NORMAL)
        self._add_btn.config(state=tk.NORMAL)

    def _add_row(self):
        self._row_count += 1
        row = DerivedFieldRow(self._rows_frame, self._columns, self._row_count)
        row.frame.pack(fill=tk.X, padx=4, pady=2)
        self._rows.append(row)

    def _apply_and_proceed(self):
        derived = [d for row in self._rows if (d := row.get_derived()) is not None]
        try:
            self.db.apply_derived_fields(derived)
        except Exception as exc:
            messagebox.showerror("Derived Fields Error", str(exc))
            return
        print(f"[DERIVED] {len(derived)} derived field(s) applied")
        self.on_applied(derived)
