import base64
import io
import json

import qrcode


def generate_qr_png_base64(data: dict) -> str:
    """Genera un QR PNG codificato in base64 a partire da un dizionario Python."""
    payload = json.dumps(data, ensure_ascii=False)
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")
