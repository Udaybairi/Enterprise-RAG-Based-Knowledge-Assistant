"""Generate realistic sample documents of every supported format for tests."""
from __future__ import annotations

import csv
from pathlib import Path

POLICY_SECTIONS = [
    ("1. Annual Leave", "Full-time employees accrue 25 days of paid annual leave per calendar year. "
     "Leave requests must be submitted through the HR portal at least two weeks in advance. "
     "Unused leave of up to five days may be carried over to the next year."),
    ("2. Remote Work", "Employees may work remotely up to three days per week with manager approval. "
     "A secure VPN connection is mandatory when accessing internal systems from outside the office. "
     "Remote workers receive a home-office stipend of 500 euros per year."),
    ("3. Expense Reimbursement", "Business expenses must be submitted within 30 days with original receipts. "
     "Travel bookings above 1000 euros require prior approval from the finance department. "
     "Reimbursements are paid with the next monthly payroll."),
]


def make_pdf(path: Path, pages: int = 3) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    for i in range(pages):
        title, body = POLICY_SECTIONS[i % len(POLICY_SECTIONS)]
        c.setFont("Helvetica", 8)
        c.drawString(72, 810, "ACME Corp - Employee Handbook - Confidential")
        c.setFont("Helvetica-Bold", 14)
        c.drawString(72, 760, title)
        c.setFont("Helvetica", 10)
        y = 735
        line = ""
        for word in body.split():
            if len(line) + len(word) > 90:
                c.drawString(72, y, line)
                y -= 14
                line = ""
            line += word + " "
        c.drawString(72, y, line)
        c.setFont("Helvetica", 8)
        c.drawString(290, 30, f"Page {i + 1} of {pages}")
        c.showPage()
    c.save()
    return path


def make_docx(path: Path) -> Path:
    import docx

    d = docx.Document()
    d.add_heading("Employee Handbook", 0)
    for title, body in POLICY_SECTIONS:
        d.add_heading(title, level=1)
        d.add_paragraph(body)
    t = d.add_table(rows=3, cols=2)
    for r, (a, b) in enumerate([("Benefit", "Value"), ("Gym", "50 euros/month"), ("Lunch", "Subsidised")]):
        t.cell(r, 0).text, t.cell(r, 1).text = a, b
    d.save(str(path))
    return path


def make_pptx(path: Path) -> Path:
    from pptx import Presentation

    prs = Presentation()
    for title, body in POLICY_SECTIONS:
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = title
        s.placeholders[1].text = body
    prs.save(str(path))
    return path


def make_xlsx(path: Path) -> Path:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Offices"
    ws.append(["City", "Employees", "Opened"])
    for row in [("Berlin", 120, 2015), ("Lisbon", 85, 2019), ("Toronto", 60, 2021)]:
        ws.append(row)
    wb.save(str(path))
    return path


def make_csv(path: Path) -> Path:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["product", "price", "warranty_years"])
        w.writerows([("Laptop Pro", 1999, 3), ("Monitor 27", 349, 2), ("Dock", 199, 1)])
    return path


def make_markdown(path: Path) -> Path:
    parts = ["# Security Guidelines\n"]
    parts.append("## Passwords\nPasswords must be at least 14 characters long and rotated every 180 days. "
                 "Multi-factor authentication is required for all production systems.\n")
    parts.append("## Incident Response\nSecurity incidents must be reported to security@acme.example within one hour. "
                 "The on-call engineer triages incidents according to the severity matrix.\n")
    parts.append("| Severity | Response time |\n|---|---|\n| SEV1 | 15 minutes |\n| SEV2 | 1 hour |\n")
    path.write_text("\n".join(parts))
    return path


def make_txt(path: Path, text: str | None = None) -> Path:
    path.write_text(text or "Office hours are 9:00 to 17:00 from Monday to Friday. "
                            "The cafeteria is located on the ground floor of building B.")
    return path
