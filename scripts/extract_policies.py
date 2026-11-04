"""Turn the store manual (PDF) into a clean Markdown file, one heading per section.

Needs the `pdftotext` tool (poppler). Only run this if you change the PDF.
The result is committed as data/politicas_da_loja.md, so normal use does not need poppler.

    python scripts/extract_policies.py
"""
import re
import subprocess
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

raw = subprocess.run(
    ["pdftotext", "-layout", str(DATA / "politicas_da_loja.pdf"), "-"],
    check=True, capture_output=True, text=True,
).stdout.replace("​", "")  # the PDF has invisible zero-width spaces

out = []
for line in raw.splitlines():
    if re.match(r"^\s*Página \d+\s*$", line) or "Manual de Políticas e Procedimentos" in line and "Empório" in line:
        continue  # page footer / running header
    if "\f" in line:
        line = line.replace("\f", "")
    if not line.strip():
        out.append("")
        continue
    if re.match(r"^\d+\.\d+\s+\S", line):          # 4.1 Direito de Arrependimento
        out.append("### " + line.strip())
    elif re.match(r"^\d+\.\s+[A-ZÀ-Ú]", line):     # 4. Política de Trocas e Devoluções
        out.append("## " + line.strip())
    elif re.match(r"^\s*•\s*", line):              # bullet
        out.append("- " + re.sub(r"^\s*•\s*", "", line).strip())
    elif re.search(r"\S {3,}\S", line):            # table row: columns are split by 3+ spaces
        out.append("| " + " | ".join(c for c in re.split(r" {3,}", line.strip()) if c) + " |")
    else:
        out.append(line.strip())

def tidy(lines: list[str]) -> list[str]:
    """Join text the PDF layout broke: wrapped bullets/cells, and gaps inside tables."""
    result: list[str] = []
    for line in lines:
        prev = result[-1] if result else ""
        if line == "":
            result.append(line)
            continue
        plain = not line.startswith(("#", "-", "|")) and not re.match(r"^\d+\.\s", line)
        # A bullet that wrapped onto the next line, or a table cell that wrapped.
        if plain and prev.startswith("-"):
            result[-1] = prev + " " + line
        elif plain and prev.startswith("|") and line[0].islower():
            result[-1] = prev[:-2] + " " + line + " |"
        else:
            result.append(line)
    # Remove blank lines between two table rows.
    cleaned: list[str] = []
    for i, line in enumerate(result):
        if line == "" and cleaned and cleaned[-1].startswith("|"):
            nxt = next((x for x in result[i + 1:] if x != ""), "")
            if nxt.startswith("|"):
                continue
        cleaned.append(line)
    return cleaned


text = re.sub(r"\n{3,}", "\n\n", "\n".join(tidy(out))).strip() + "\n"
(DATA / "politicas_da_loja.md").write_text(text, encoding="utf-8")
print(f"Wrote {DATA / 'politicas_da_loja.md'} ({len(text)} characters)")
