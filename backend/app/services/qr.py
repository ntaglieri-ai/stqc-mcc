import base64
import io
import json
import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import qrcode

_BASE_URL = "https://stqc.mcc.eu/p"
_QR_CACHE_DIR = Path(__file__).resolve().parents[3] / "uploads" / "qr-cache"


def generate_qr_for_uuid(item_uuid: str) -> str:
    """QR per un pezzo fisico o un item di magazzino.
    Payload: URL con solo UUID — nessun dato che possa diventare obsoleto.
    """
    url = f"{_BASE_URL}/{item_uuid}"
    return _make_qr_png_base64(url)


def generate_qr_for_payload(payload: str) -> str:
    """QR con payload testuale esatto, usato per codici pezzo leggibili."""
    return _make_qr_png_base64(payload)


def generate_qr_png_base64(data: dict) -> str:
    """Legacy: genera QR da un dizionario (usato da endpoint vecchi)."""
    return _make_qr_png_base64(json.dumps(data, ensure_ascii=False))


@lru_cache(maxsize=10000)
def _make_qr_png_base64(payload: str) -> str:
    cache_path = _QR_CACHE_DIR / f"{hashlib.sha256(payload.encode('utf-8')).hexdigest()}.b64"
    try:
        cached = cache_path.read_text(encoding="ascii")
        if cached:
            return cached
    except (FileNotFoundError, OSError):
        pass
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    try:
        _QR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_text(encoded, encoding="ascii")
        os.replace(temporary, cache_path)
    except OSError:
        pass
    return encoded


def warm_qr_payload_cache(payloads: list[str], workers: int = 4) -> None:
    """Prepara in background i QR persistenti prima che l'utente stampi."""
    clean = list(dict.fromkeys(str(payload) for payload in payloads if payload))
    if not clean:
        return
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as executor:
        list(executor.map(generate_qr_for_payload, clean))
