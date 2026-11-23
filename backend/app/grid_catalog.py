from pathlib import Path
from openpyxl import load_workbook
import fitz

def workbook_catalog(path: Path) -> list[dict]:
    wb=load_workbook(path, data_only=True, read_only=True)
    out=[]
    for ws in wb.worksheets:
        nonempty=0
        samples=[]
        for row in ws.iter_rows():
            vals=[c.value for c in row]
            if any(v is not None for v in vals):
                nonempty+=1
                if len(samples)<8:
                    samples.append({"row":row[0].row,"cells":{c.coordinate:str(c.value)[:180] for c in row if c.value is not None}})
        out.append({"file":path.name,"sheet":ws.title,"max_row":ws.max_row,"max_column":ws.max_column,"nonempty_rows":nonempty,"sample_rows":samples})
    return out

def pdf_catalog(path: Path) -> dict:
    doc=fitz.open(path)
    return {"file":path.name,"pages":[{"page":i+1,"text":p.get_text("text")[:5000]} for i,p in enumerate(doc)]}

def discover_rate_cards(root: Path) -> list[dict]:
    cards=[]
    for path in root.rglob("*"):
        if path.suffix.lower()==".xlsx":
            cards.extend(workbook_catalog(path))
        elif path.suffix.lower()==".pdf":
            cards.append(pdf_catalog(path))
    return cards
