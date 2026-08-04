import base64
import io
import math

from fpdf import FPDF
from pypdf import PdfReader, PdfWriter

from backend.app.models.commessa import Commessa, Piece
from backend.app.models.warehouse import DistintaItem
from backend.app.services.qr import generate_qr_for_payload, generate_qr_for_uuid


def commessa_display_name(commessa: Commessa | None) -> str:
    """Nome operativo stampato: descrizione importata, poi codice interno."""
    if commessa is None:
        return "COMMESSA"
    return (commessa.descrizione or commessa.codice or "COMMESSA").strip()


def format_piece_label_payload(
    commessa_name: str,
    part_number: str,
    progressivo: int,
    totale: int,
    peso_kg: float | None,
) -> str:
    """Replica il testo storico dei fogli etichette MCC."""
    name = (commessa_name or "COMMESSA").strip()
    code = (part_number or "SENZA CODICE").strip()
    current = max(1, int(progressivo or 1))
    total = max(current, int(totale or 1))
    raw_weight = float(peso_kg) if peso_kg is not None else 0
    if not math.isfinite(raw_weight):
        raw_weight = 0
    # Excel ROUND: i mezzi si arrotondano lontano dallo zero (18,5 -> 19).
    weight = math.floor(raw_weight + 0.5) if raw_weight >= 0 else math.ceil(raw_weight - 0.5)
    return f"{name} {code} Q.TA' {current} di {total} KG {weight}"


def generate_piece_label_pdf(
    piece: Piece,
    commessa: Commessa,
    totale: int,
    *,
    width_mm: float = 70,
    height_mm: float = 120,
) -> bytes:
    """Etichetta commessa parametrica, distinta dai QR di magazzino."""
    width = min(max(float(width_mm), 40), 210)
    height = min(max(float(height_mm), 40), 297)
    payload = format_piece_label_payload(
        commessa_display_name(commessa),
        piece.marca_pos,
        piece.progressivo,
        totale,
        float(piece.peso_kg) if piece.peso_kg is not None else None,
    )
    # Con un formato personalizzato FPDF usa la tupla come pagina base: mantenere
    # P evita che larghezza e altezza vengano invertite una seconda volta.
    pdf = FPDF(orientation="P", unit="mm", format=(width, height))
    pdf.set_margins(4, 4, 4)
    pdf.set_auto_page_break(False)
    pdf.add_page()

    qr_bytes = base64.b64decode(generate_qr_for_payload(payload))
    qr_side = min(width * 0.48, height * 0.42)
    qr_x = 5
    qr_y = 6
    pdf.image(io.BytesIO(qr_bytes), x=qr_x, y=qr_y, w=qr_side, h=qr_side)

    pdf.set_xy(qr_x + qr_side + 2, qr_y + qr_side * 0.24)
    pdf.set_font("Helvetica", "B", max(16, min(28, int(width * 0.35))))
    pdf.cell(max(1, width - (qr_x + qr_side + 6)), 12, "MCC", align="C")

    text_y = min(height - 24, qr_y + qr_side + 4)
    pdf.set_xy(4, text_y)
    pdf.set_font("Helvetica", "B", max(8, min(12, int(width / 7))))
    pdf.multi_cell(width - 8, 6, payload, align="C")
    return bytes(pdf.output())


def generate_piece_labels_pdf(
    labels: list[tuple[Piece, Commessa, int]],
    *,
    width_mm: float = 70,
    height_mm: float = 120,
) -> bytes:
    """Unisce più etichette MCC, una pagina per ogni pezzo selezionato."""
    writer = PdfWriter()
    for piece, commessa, totale in labels:
        single = generate_piece_label_pdf(
            piece,
            commessa,
            totale,
            width_mm=width_mm,
            height_mm=height_mm,
        )
        writer.append(PdfReader(io.BytesIO(single)))
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def generate_label_pdf(item: DistintaItem) -> bytes:
    """Genera un PDF etichetta A6 (105x148 mm) con QR e dati del pezzo."""
    piece_code = item.part_number or "-"
    if item.part_number and item.instance_number is not None:
        piece_code = f"{item.part_number}-{int(item.instance_number):03d}"
    pdf = FPDF(orientation="P", unit="mm", format=(105, 148))
    pdf.set_margins(8, 8, 8)
    pdf.set_auto_page_break(False)
    pdf.add_page()

    # --- QR image (se presente) ---
    if item.qr_attivo:
        try:
            from PIL import Image

            qr_bytes = base64.b64decode(item.qr_code or generate_qr_for_uuid(item.uuid))
            img = Image.open(io.BytesIO(qr_bytes))
            tmp = io.BytesIO()
            img.save(tmp, format="PNG")
            tmp.seek(0)
            pdf.image(tmp, x=29, y=8, w=48, h=48)
        except Exception:
            pass

    # --- Titolo ---
    pdf.set_y(60)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "STQC - MCC Srl", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, "Etichetta pezzo", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # --- Dati pezzo ---
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(35, 7, "Pos. / Parte:", new_x="END", new_y="LAST")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 7, piece_code, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(35, 7, "Profilo:", new_x="END", new_y="LAST")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 7, item.description or "-")

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(35, 7, "Materiale:", new_x="END", new_y="LAST")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 7, item.material_code or "-", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(35, 7, "Quantità:", new_x="END", new_y="LAST")
    pdf.set_font("Helvetica", "", 10)
    qty_str = str(int(item.quantity)) if item.quantity and item.quantity == int(item.quantity) else str(item.quantity or "-")
    pdf.cell(0, 7, qty_str, new_x="LMARGIN", new_y="NEXT")

    if item.commessa_reference:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(35, 7, "Commessa:", new_x="END", new_y="LAST")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 7, item.commessa_reference, new_x="LMARGIN", new_y="NEXT")

    # --- Footer con codice leggibile ---
    pdf.set_y(-15)
    pdf.set_font("Helvetica", "I", 7)
    pdf.cell(0, 5, f"QR: {piece_code}", align="C")

    return bytes(pdf.output())
