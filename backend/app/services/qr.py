import base64
import io
import json

import qrcode

_BASE_URL = "https://stqc.mcc.eu/p"


def generate_qr_for_uuid(item_uuid: str) -> str:
    """QR per un pezzo fisico o un item di magazzino.
    Payload: URL con solo UUID — nessun dato che possa diventare obsoleto.
    """
    url = f"{_BASE_URL}/{item_uuid}"
    return _make_qr_png_base64(url)


def generate_qr_png_base64(data: dict) -> str:
    """Legacy: genera QR da un dizionario (usato da endpoint vecchi)."""
    return _make_qr_png_base64(json.dumps(data, ensure_ascii=False))


def _make_qr_png_base64(payload: str) -> str:
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")
