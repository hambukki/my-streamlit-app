"""TXT, CSV, DOCX, PPTX, PDF, XLSX 내용 추출."""
import csv
import io
from itertools import islice
from pathlib import Path


def decode_text_file(raw):
    for encoding in ("utf-8-sig", "utf-16", "cp949"):
        try:
            return raw.decode(encoding)
        except (UnicodeError, LookupError):
            pass
    raise ValueError("파일 인코딩을 확인해주세요. UTF-8 또는 CP949를 권장합니다.")


def extract_document(file):
    """업로드 파일을 외부 URL에 노출하지 않고 업무용 텍스트로 추출합니다."""
    filename = getattr(file, "name", "첨부파일")
    suffix = Path(filename).suffix.lower()
    raw = file.getvalue()
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError(f"{filename}: 파일당 8MB 이하만 지원합니다.")
    if suffix in (".txt", ".md", ".csv"):
        content = decode_text_file(raw)
        if suffix == ".csv":
            lines = list(csv.reader(io.StringIO(content)))[:400]
            return "\n".join(" | ".join(row) for row in lines)[:25000]
        return content[:25000]
    if suffix == ".docx":
        from docx import Document
        doc = Document(io.BytesIO(raw))
        lines = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                lines.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(lines)[:25000]
    if suffix == ".pptx":
        from pptx import Presentation
        presentation = Presentation(io.BytesIO(raw))
        chunks = []
        for idx, slide in enumerate(presentation.slides, 1):
            chunks.append(f"[슬라이드 {idx}]")
            for shape in slide.shapes:
                if shape.has_text_frame and shape.text.strip():
                    chunks.append(shape.text)
                if shape.has_table:
                    for row in shape.table.rows:
                        chunks.append(" | ".join(c.text for c in row.cells))
        return "\n".join(chunks)[:25000]
    if suffix == ".pdf":
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in
                         PdfReader(io.BytesIO(raw)).pages[:30])[:25000]
    if suffix == ".xlsx":
        from openpyxl import load_workbook
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        chunks = []
        for sheet in workbook.worksheets[:4]:
            chunks.append(f"[시트 {sheet.title}]")
            for row in islice(sheet.iter_rows(values_only=True), 250):
                chunks.append(" | ".join(str(v) if v is not None else "" for v in row))
        workbook.close()
        return "\n".join(chunks)[:25000]
    if suffix in (".doc", ".ppt"):
        raise ValueError(f"{filename}: 구형 형식은 .docx 또는 .pptx로 변환해주세요.")
    raise ValueError(f"{filename}: 지원하지 않는 파일 형식입니다.")
