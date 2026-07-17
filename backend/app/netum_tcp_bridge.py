"""Bridge TCP per scanner NETUM Wi-Fi.

La pistola NETUM DS2800 in modalità Wi-Fi invia il testo letto a un servizio
TCP, non a un endpoint HTTP. Questo bridge ascolta su una porta TCP locale,
riceve il payload grezzo e lo inoltra alla logica scanner STQC usando la
configurazione della pistola salvata a DB:

- scan_mode = MAGAZZINO -> pre-produzione grezzo/pezzi
- scan_mode = OFFICINA  -> officina postazioni/fasi/tempi
"""
from __future__ import annotations

import argparse
import os
import socketserver
from datetime import datetime

from sqlalchemy.orm import Session

from backend.app.db.session import SessionLocal
from backend.app.models.commessa import ScannerDevice
from backend.app.services.preproduction_scan import process_preproduction_scan
from backend.app.services.workshop_scan import process_workshop_scan


def _scanner_for_bridge(db: Session, scanner_code: str | None, device_token: str | None) -> ScannerDevice:
    query = db.query(ScannerDevice).filter(ScannerDevice.active.is_(True))
    if device_token:
        scanner = query.filter(ScannerDevice.device_token == device_token).first()
    elif scanner_code:
        scanner = query.filter(ScannerDevice.scanner_code == scanner_code).first()
    else:
        scanner = query.filter(ScannerDevice.scan_mode == "MAGAZZINO").order_by(ScannerDevice.id).first()
    if not scanner:
        target = device_token or scanner_code or "prima pistola MAGAZZINO attiva"
        raise RuntimeError(f"Scanner non trovato o non attivo: {target}")
    return scanner


def _process_payload(payload: str, scanner_code: str | None, device_token: str | None) -> dict:
    db = SessionLocal()
    try:
        scanner = _scanner_for_bridge(db, scanner_code, device_token)
        external_id = f"NETUM-TCP-{datetime.utcnow().timestamp()}"
        mode = (scanner.scan_mode or "OFFICINA").upper()
        if mode == "MAGAZZINO":
            result = process_preproduction_scan(db, scanner, payload, external_id)
        else:
            result = process_workshop_scan(db, scanner, payload, external_id)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class NetumTCPHandler(socketserver.BaseRequestHandler):
    scanner_code: str | None = None
    device_token: str | None = None

    def handle(self) -> None:
        self.request.settimeout(0.8)
        chunks: list[bytes] = []
        while True:
            try:
                data = self.request.recv(4096)
            except TimeoutError:
                break
            except OSError:
                break
            if not data:
                break
            chunks.append(data)
            if b"\n" in data or b"\r" in data:
                break

        raw = b"".join(chunks).decode("utf-8", errors="ignore")
        payloads = [part.strip() for part in raw.replace("\r", "\n").split("\n") if part.strip()]
        if not payloads and raw.strip():
            payloads = [raw.strip()]

        for payload in payloads:
            try:
                result = _process_payload(payload, self.scanner_code, self.device_token)
                print(f"[NETUM TCP] OK {self.client_address[0]} payload={payload!r} result={result.get('msg')!r}", flush=True)
            except Exception as exc:
                print(f"[NETUM TCP] ERROR {self.client_address[0]} payload={payload!r} error={exc}", flush=True)

        try:
            self.request.sendall(b"OK\n")
        except OSError:
            pass


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    parser = argparse.ArgumentParser(description="Bridge TCP NETUM -> STQC scanner logic")
    parser.add_argument("--host", default=os.getenv("NETUM_TCP_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("NETUM_TCP_PORT", "9100")))
    parser.add_argument("--scanner-code", default=os.getenv("NETUM_SCANNER_CODE"))
    parser.add_argument("--device-token", default=os.getenv("NETUM_DEVICE_TOKEN"))
    args = parser.parse_args()

    NetumTCPHandler.scanner_code = args.scanner_code
    NetumTCPHandler.device_token = args.device_token

    label = args.device_token or args.scanner_code or "prima pistola MAGAZZINO attiva"
    print(f"[NETUM TCP] ascolto su {args.host}:{args.port} -> {label}", flush=True)
    with ThreadedTCPServer((args.host, args.port), NetumTCPHandler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
