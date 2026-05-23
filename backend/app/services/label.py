import base64
import io

from fpdf import FPDF

from backend.app.models.warehouse import DistintaItem


def generate_label_pdf(item: DistintaItem) -> bytes:
    """Genera un PDF etichetta A6 (105x148 mm) con QR e dati del pezzo."""
    pdf = FPDF(orientation="P", unit="mm", format=(105, 148))
    pdf.set_margins(8, 8, 8)
    pdf.add_page()

    # --- QR image (se presente) ---
    if item.qr_code:
        try:
            from PIL import Image

            qr_bytes = base64.b64decode(item.qr_code)
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
    pdf.cell(0, 7, item.part_number or "-", new_x="LMARGIN", new_y="NEXT")

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

    # --- Footer con item_id ---
    pdf.set_y(-15)
    pdf.set_font("Helvetica", "I", 7)
    pdf.cell(0, 5, f"ID: {item.id}", align="C")

    return pdf.output()
