import base64
import io
import math

from fpdf import FPDF
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
    name = (commessa_name or "COMMESSA").strip().upper()
    code = (part_number or "SENZA CODICE").strip().upper()
    current = max(1, int(progressivo or 1))
    total = max(current, int(totale or 1))
    raw_weight = float(peso_kg) if peso_kg is not None else 0
    if not math.isfinite(raw_weight):
        raw_weight = 0
    # Excel ROUND: i mezzi si arrotondano lontano dallo zero (18,5 -> 19).
    weight = math.floor(raw_weight + 0.5) if raw_weight >= 0 else math.ceil(raw_weight - 0.5)
    return f"{name} {code} Q.TA' {current} DI {total} KG {weight}"


def _draw_piece_label(pdf: FPDF, piece: Piece, commessa: Commessa, totale: int,
                      x: float, y: float, width: float = 70, height: float = 50) -> None:
    """Disegna un'etichetta orizzontale con bordo di taglio visibile."""
    payload = format_piece_label_payload(
        commessa_display_name(commessa), piece.marca_pos, piece.progressivo, totale,
        float(piece.peso_kg) if piece.peso_kg is not None else None,
    )
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.35)
    pdf.rect(x, y, width, height)
    cached_qr = getattr(piece, "_label_qr_base64", None)
    qr_bytes = base64.b64decode(cached_qr or generate_qr_for_payload(payload))
    qr_side = min(28.0, height - 20, width * 0.42)
    qr_x, qr_y = x + 3, y + 3
    pdf.image(io.BytesIO(qr_bytes), x=qr_x, y=qr_y, w=qr_side, h=qr_side)

    logo_x = qr_x + qr_side + 1
    logo_width = x + width - logo_x - 3
    pdf.set_xy(logo_x, y + 9)
    pdf.set_font("Helvetica", "B", 24)
    pdf.cell(logo_width, 11, "MCC", align="L")

    first_line, quantity_line = payload.rsplit(" Q.TA'", 1)
    quantity_line = "Q.TA'" + quantity_line
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_xy(x + 2, y + 33)
    pdf.cell(width - 4, 6.5, first_line, align="C")
    pdf.set_xy(x + 2, y + 40.5)
    pdf.cell(width - 4, 6.5, quantity_line, align="C")


def _required_piece_label_width(piece: Piece, commessa: Commessa, totale: int) -> float:
    """Larghezza necessaria per mantenere entrambe le righe intere."""
    payload = format_piece_label_payload(
        commessa_display_name(commessa), piece.marca_pos, piece.progressivo, totale,
        float(piece.peso_kg) if piece.peso_kg is not None else None,
    )
    first_line, quantity_line = payload.rsplit(" Q.TA'", 1)
    quantity_line = "Q.TA'" + quantity_line
    measure = FPDF(unit="mm")
    measure.set_font("Helvetica", "B", 12)
    text_width = max(measure.get_string_width(first_line), measure.get_string_width(quantity_line))
    return min(190.0, max(70.0, text_width + 6.0))

def generate_piece_label_pdf(piece: Piece, commessa: Commessa, totale: int, *,
                             width_mm: float = 70, height_mm: float = 50) -> bytes:
    """Etichetta orizzontale alta 50 mm e larga quanto richiede il testo."""
    width = max(min(max(float(width_mm), 40), 70), _required_piece_label_width(piece, commessa, totale))
    height = min(max(float(height_mm), 40), 50)
    pdf = FPDF(orientation="L", unit="mm", format=(height, width))
    pdf.set_margins(0, 0, 0); pdf.set_auto_page_break(False); pdf.add_page()
    _draw_piece_label(pdf, piece, commessa, totale, 0, 0, width, height)
    return bytes(pdf.output())


def generate_piece_labels_pdf(labels: list[tuple[Piece, Commessa, int]], *,
                              width_mm: float = 70, height_mm: float = 50) -> bytes:
    """Crea una pagina PDF indipendente per ogni etichetta selezionata."""
    base_width = min(max(float(width_mm), 40), 70)
    width = max([base_width, *(_required_piece_label_width(*label) for label in labels)])
    height = min(max(float(height_mm), 40), 50)
    pdf = FPDF(orientation="P", unit="mm", format=(width, height))
    pdf.set_margins(0, 0, 0)
    pdf.set_auto_page_break(False)
    for piece, commessa, totale in labels:
        pdf.add_page()
        _draw_piece_label(pdf, piece, commessa, totale, 0, 0, width, height)
    return bytes(pdf.output())

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
