# STQC-MCC

Progetto backend di prova per STQC — Sistema di Tracciamento QR su Commessa per MCC Srl.

## Stack tecnico

- Backend: Python + FastAPI
- Database: SQLite
- Deploy: Docker

## Struttura iniziale

- `backend/app/main.py`: avvia l'app FastAPI
- `backend/app/api/api_v1/endpoints/warehouse.py`: API iniziali per il magazzino
- `backend/app/models/warehouse.py`: modelli SQLAlchemy per fornitori, materiali, lotti, ricezioni, certificati e movimenti
- `backend/app/schemas/warehouse.py`: schemi Pydantic per le API
- `backend/app/schemas/distinta.py`: schemi Pydantic per import distinta
- `backend/app/crud/warehouse.py`: logica CRUD magazzino
- `backend/app/crud/distinta.py`: logica CRUD import distinta
- `backend/app/services/distinta.py`: parsing base `.xlsx` per distinte
- `backend/app/db/session.py`: connessione SQLite

## Endpoints principali

**Magazzino**
- `POST/GET /api/v1/warehouse/suppliers` — fornitori
- `GET /api/v1/warehouse/suppliers/{id}`
- `POST/GET /api/v1/warehouse/materials` — materiali
- `GET /api/v1/warehouse/materials/{id}`
- `POST/GET /api/v1/warehouse/batches` — lotti
- `GET /api/v1/warehouse/batches/{id}`
- `POST/GET /api/v1/warehouse/receipts` — ricezioni DDT
- `POST /api/v1/warehouse/movements` — movimenti stock
- `GET /api/v1/warehouse/stock/{material_id}` — saldo materiale

**Certificati**
- `POST /api/v1/warehouse/receipts/{id}/certificates` — upload PDF/file
- `GET /api/v1/warehouse/receipts/{id}/certificates` — lista certificati
- `GET /api/v1/warehouse/receipts/certificates/{cert_id}/download` — download file

**Distinte**
- `POST /api/v1/warehouse/distinta/import` — import `.xlsx` / `.xlsm` / `.xls`
- `GET /api/v1/warehouse/distinta/imports` — lista importazioni
- `GET /api/v1/warehouse/distinta/imports/{id}` — dettaglio importazione
- `GET /api/v1/warehouse/distinta/items/{id}/label.pdf` — etichetta PDF A6 con QR

**QR**
- `POST /api/v1/qr/scan` — decodifica payload QR, restituisce dati pezzo
- `GET /api/v1/qr/item/{item_id}` — accesso diretto per ID

**Commesse**
- `POST/GET /api/v1/commesse`
- `GET/PATCH/DELETE /api/v1/commesse/{id}`

## Avvio locale

1. Installare le dipendenze:

```bash
python -m pip install -r requirements.txt
```

2. Avviare l'app:

```bash
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

3. Aprire la documentazione automatica:

- `http://127.0.0.1:8000/docs`

## Avvio con Docker

```bash
docker compose up --build
```

L'applicazione sarà disponibile su `http://127.0.0.1:8000`.

**Testing locale rapido**

- Creare e attivare l'ambiente virtuale:

```bash
cd /Users/imacnando/Desktop/stqc-mcc
python3 -m venv venv
. venv/bin/activate
```

- Installare le dipendenze (requirements aggiornati per Python 3.14):

```bash
python -m pip install -r requirements.txt
```

- Importare una distinta direttamente in DB (script di test):

```bash
python tools/import_local.py "2553 - Lista parti assemblaggi_r01.xls"
```

- Avviare il server FastAPI e aprire Swagger UI:

```bash
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
# then open http://127.0.0.1:8000/docs
```

**Endpoint principali**

- `POST /api/v1/warehouse/distinta/import` — upload file `.xls` / `.xlsx` / `.xlsm`. Parametro opzionale `generate_qr=true` per generare QR (base64 PNG) per ogni pezzo.
- `GET /api/v1/warehouse/distinta/imports` — lista importazioni salvate.

Supported parsers:
- parser specifico `Lista parti assemblaggi` (Tekla/Advanced Steel style)
- parser generico per distinte (`parse_distinta_file`)

Nota: se vedi warning relativi a `pydantic` (es. `orm_mode`), sono avvisi di compatibilità non bloccanti. Se preferisci, posso creare un branch con dipendenze pinneate per una specifica versione di Python (es. 3.11).

Esempi d'uso (curl / Python)

- Upload semplice con `curl`:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/warehouse/distinta/import" \
	-F "file=@\"2553 - Lista parti assemblaggi_r01.xls\""
```

- Upload con richiesta di generare i QR (query param `generate_qr=true`):

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/warehouse/distinta/import?generate_qr=true" \
	-F "file=@\"2553 - Lista parti assemblaggi_r01.xls\""
```

- Esempio con Python `requests` (upload e stampa JSON di risposta):

```python
import requests

url = "http://127.0.0.1:8000/api/v1/warehouse/distinta/import?generate_qr=true"
files = {"file": open('2553 - Lista parti assemblaggi_r01.xls', 'rb')}
resp = requests.post(url, files=files)
print(resp.status_code)
print(resp.json())
```

Puoi anche usare l'interfaccia Swagger in `http://127.0.0.1:8000/docs` per caricare file e vedere direttamente la struttura della risposta.
