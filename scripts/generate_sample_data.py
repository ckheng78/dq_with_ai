"""
Generates sample SAP HR infotype CSV files:
  PA0000 - Actions
  PA0001 - Organisational Assignment
  PA0002 - Personal Data
"""
import csv
import os
import random
from datetime import date, timedelta

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
MANDT = "100"
HIGH_DATE = "9999-12-31"

random.seed(42)


def fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")


# ── Reference data ────────────────────────────────────────────────────────────

EMPLOYEES = [
    # (PERNR, first, last, gender, dob,          title, nationality, marital)
    ("00000001", "James",     "Harrison",   "1", "1985-03-14", "Mr",  "GB", "M"),
    ("00000002", "Sarah",     "Mitchell",   "2", "1990-07-22", "Ms",  "GB", "S"),
    ("00000003", "Mohammed",  "Al-Rashid",  "1", "1978-11-05", "Mr",  "SA", "M"),
    ("00000004", "Emily",     "Thompson",   "2", "1992-01-30", "Ms",  "GB", "S"),
    ("00000005", "David",     "Chen",       "1", "1983-09-18", "Mr",  "SG", "M"),
    ("00000006", "Priya",     "Sharma",     "2", "1995-04-12", "Ms",  "IN", "S"),
    ("00000007", "Robert",    "Williams",   "1", "1975-06-28", "Mr",  "US", "M"),
    ("00000008", "Amanda",    "Jones",      "2", "1988-12-03", "Mrs", "GB", "M"),
    ("00000009", "Liam",      "O'Brien",    "1", "1993-08-15", "Mr",  "IE", "S"),
    ("00000010", "Fatima",    "Hassan",     "2", "1987-02-20", "Ms",  "NG", "M"),
    ("00000011", "Thomas",    "Müller",     "1", "1980-05-07", "Mr",  "DE", "M"),
    ("00000012", "Charlotte", "Davies",     "2", "1997-10-25", "Ms",  "GB", "S"),
    ("00000013", "Kevin",     "Okonkwo",    "1", "1986-03-31", "Mr",  "NG", "M"),
    ("00000014", "Sophie",    "Leclerc",    "2", "1991-07-14", "Ms",  "FR", "S"),
    ("00000015", "Daniel",    "Kowalski",   "1", "1984-01-09", "Mr",  "PL", "M"),
    ("00000016", "Grace",     "Tan",        "2", "1994-11-18", "Ms",  "MY", "S"),
    ("00000017", "Andrew",    "MacGregor",  "1", "1979-04-23", "Mr",  "GB", "M"),
    ("00000018", "Aisha",     "Patel",      "2", "1996-08-07", "Ms",  "GB", "S"),
    ("00000019", "Marcus",    "Johnson",    "1", "1982-12-30", "Mr",  "US", "M"),
    ("00000020", "Yuki",      "",           "2", "1989-06-16", "Ms",  "JP", "S"),  # missing last name — DQ test
]

ORG_UNITS = [
    ("1000", "GB01", "GB10", "1", "U1", "30000001", "50000001", "60000001", "MO"),  # Finance
    ("1000", "GB01", "GB10", "1", "U1", "30000002", "50000002", "60000002", "MO"),  # HR
    ("1000", "GB01", "GB20", "1", "U2", "30000003", "50000003", "60000003", "MO"),  # IT
    ("1000", "GB01", "GB20", "1", "U2", "30000004", "50000004", "60000004", "MO"),  # Operations
    ("2000", "US01", "US10", "1", "U3", "30000005", "50000005", "60000005", "SM"),  # US Sales
]

# MASSN: action type codes
MASSN_HIRE     = "01"
MASSN_TRANSFER = "12"
MASSN_LEAVE    = "14"
MASSN_TERM     = "10"

# STAT2: employment status
STAT2_ACTIVE   = "3"
STAT2_INACTIVE = "0"

# ── Helpers ───────────────────────────────────────────────────────────────────

def hire_date(dob_str: str) -> date:
    dob = date.fromisoformat(dob_str)
    # hired roughly 22-30 years after birth
    years_after = random.randint(22, 30)
    return date(dob.year + years_after, random.randint(1, 12), random.randint(1, 28))


# ── PA0000 — Actions ──────────────────────────────────────────────────────────

def build_pa0000():
    rows = []
    for emp in EMPLOYEES:
        pernr = emp[0]
        dob = emp[4]
        hd = hire_date(dob)

        # Hiring action
        rows.append({
            "MANDT": MANDT,
            "PERNR": pernr,
            "BEGDA": fmt(hd),
            "ENDDA": HIGH_DATE,
            "SEQNR": "000",
            "MASSN": MASSN_HIRE,
            "MASSN_TEXT": "Hiring",
            "MASSG": "01",
            "MASSG_TEXT": "New Employee",
            "STAT2": STAT2_ACTIVE,
            "STAT2_TEXT": "Active",
        })

        # ~30% chance of a transfer
        if random.random() < 0.3:
            transfer_date = hd + timedelta(days=random.randint(365, 1200))
            if transfer_date < date.today():
                rows.append({
                    "MANDT": MANDT,
                    "PERNR": pernr,
                    "BEGDA": fmt(transfer_date),
                    "ENDDA": HIGH_DATE,
                    "SEQNR": "001",
                    "MASSN": MASSN_TRANSFER,
                    "MASSN_TEXT": "Transfer",
                    "MASSG": "05",
                    "MASSG_TEXT": "Internal Transfer",
                    "STAT2": STAT2_ACTIVE,
                    "STAT2_TEXT": "Active",
                })

    # Introduce one terminated employee (DQ test: terminated but still has active records)
    term_date = date(2023, 6, 30)
    rows.append({
        "MANDT": MANDT,
        "PERNR": "00000008",
        "BEGDA": fmt(term_date),
        "ENDDA": HIGH_DATE,
        "SEQNR": "002",
        "MASSN": MASSN_TERM,
        "MASSN_TEXT": "Termination",
        "MASSG": "10",
        "MASSG_TEXT": "Resignation",
        "STAT2": STAT2_INACTIVE,
        "STAT2_TEXT": "Inactive",
    })

    return rows


# ── PA0001 — Organisational Assignment ───────────────────────────────────────

def build_pa0001():
    rows = []
    for i, emp in enumerate(EMPLOYEES):
        pernr = emp[0]
        dob = emp[4]
        hd = hire_date(dob)
        org = ORG_UNITS[i % len(ORG_UNITS)]
        bukrs, werks, btrtl, persg, persk, kostl, orgeh, plans, abkrs = org

        rows.append({
            "MANDT": MANDT,
            "PERNR": pernr,
            "BEGDA": fmt(hd),
            "ENDDA": HIGH_DATE,
            "SEQNR": "000",
            "BUKRS": bukrs,
            "BUKRS_TEXT": "UK Operations" if bukrs == "1000" else "US Operations",
            "WERKS": werks,
            "WERKS_TEXT": "London HQ" if werks == "GB01" else "New York",
            "BTRTL": btrtl,
            "PERSG": persg,
            "PERSG_TEXT": "Active Employee",
            "PERSK": persk,
            "PERSK_TEXT": "Salaried Staff",
            "KOSTL": kostl,
            "ORGEH": orgeh,
            "PLANS": plans,
            "ABKRS": abkrs,
            "ABKRS_TEXT": "Monthly" if abkrs == "MO" else "Semi-Monthly",
        })

    # One employee with missing cost centre (DQ test)
    rows[4]["KOSTL"] = ""

    return rows


# ── PA0002 — Personal Data ────────────────────────────────────────────────────

def build_pa0002():
    rows = []
    for emp in EMPLOYEES:
        pernr, first, last, gender, dob, title, nationality, marital = emp
        hd = hire_date(dob)

        rows.append({
            "MANDT": MANDT,
            "PERNR": pernr,
            "BEGDA": fmt(hd),
            "ENDDA": HIGH_DATE,
            "SEQNR": "000",
            "ANRED": title,
            "VORNA": first,
            "NACHN": last,
            "GESCH": gender,
            "GESCH_TEXT": "Male" if gender == "1" else "Female",
            "GBDAT": dob,
            "FAMST": marital,
            "FAMST_TEXT": "Married" if marital == "M" else "Single",
            "NATIO": nationality,
        })

    # One employee with missing date of birth (DQ test)
    rows[11]["GBDAT"] = ""

    return rows


# ── Write CSVs ────────────────────────────────────────────────────────────────

def write_csv(filename: str, rows: list[dict]):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"Written: {path}  ({len(rows)} rows)")


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    write_csv("PA0000.csv", build_pa0000())
    write_csv("PA0001.csv", build_pa0001())
    write_csv("PA0002.csv", build_pa0002())
    print("Done.")
