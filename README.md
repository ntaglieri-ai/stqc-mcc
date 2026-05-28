# STQC-MCC

Sistema di Tracciamento QR su Commessa per MCC Srl — gestione magazzino, distinte, fasi operative e commesse di produzione.

## Stack tecnico

| Layer | Tecnologia |
|---|---|
| Backend | Python 3.14 + FastAPI |
| ORM | SQLAlchemy 2.x |
| Database | SQLite (file `backend/app.db`) |
| Migrazioni | Alembic |
| Autenticazione | JWT (PyJWT, HS256, scadenza 8h) |
| Frontend | Vanilla JS + HTML statico servito da FastAPI |
| Deploy | Docker Compose |

## Struttura del progetto

```
stqc-mcc/
├── backend/
│   ├── app/
│   │   ├── main.py                      # Entry point FastAPI
│   │   ├── api/api_v1/endpoints/
│   │   │   ├── auth.py                  # Login / PIN / /me
│   │   │   ├── warehouse.py             # Fornitori, materiali, lotti, ricezioni, movimenti
│   │   │   ├── distinta.py              # Import distinta, QR, etichette PDF
│   │   │   ├── commessa.py              # Commesse + fasi operative
│   │   │   ├── stock.py                 # Analisi disponibilità, prelievi, richieste
│   │   │   ├── qr.py                    # Scan QR
│   │   │   ├── inventario.py            # Import inventario
│   │   │   ├── certificates.py          # Certificati DDT
│   │   │   └── admin.py                 # Gestione utenti, log, manutenzione
│   │   ├── models/                      # Modelli SQLAlchemy
│   │   ├── schemas/                     # Schemi Pydantic
│   │   ├── crud/                        # Logica CRUD
│   │   ├── services/                    # Parser xlsx, generazione QR/PDF
│   │   ├── db/session.py                # Connessione SQLite
│   │   └── static/                      # Frontend HTML (home, magazzino, commesse…)
│   └── app.db                           # Database SQLite
├── alembic/                             # Migrazioni DB
├── tools/                               # Script di utilità locali
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

## Profili utente

| Profilo | Accesso |
|---|---|
| `Admin` | Tutto, inclusa gestione utenti e log |
| `Responsabile` | Commesse, magazzino, reportistica |
| `Operaio` | Fasi operative assegnate, scan QR |
| `Logistica` | Magazzino, movimenti, distinte |
| `Acquisti` | Fornitori, ordini (modulo WIP) |

## API Reference

### Autenticazione

| Metodo | Path | Descrizione |
|---|---|---|
| POST | `/api/v1/auth/login` | Login username+password → JWT |
| POST | `/api/v1/auth/login-pin` | Login con PIN → JWT |
| GET | `/api/v1/auth/me` | Dati utente autenticato |

### Magazzino

| Metodo | Path | Descrizione |
|---|---|---|
| POST/GET | `/api/v1/warehouse/suppliers` | Fornitori |
| GET/PATCH/DELETE | `/api/v1/warehouse/suppliers/{id}` | Fornitore singolo |
| POST/GET | `/api/v1/warehouse/materials` | Materiali |
| GET/PATCH/DELETE | `/api/v1/warehouse/materials/{id}` | Materiale singolo |
| POST/GET | `/api/v1/warehouse/batches` | Lotti |
| GET | `/api/v1/warehouse/batches/{id}` | Lotto singolo |
| POST/GET | `/api/v1/warehouse/receipts` | Ricezioni DDT |
| POST | `/api/v1/warehouse/movements` | Movimento stock |
| GET | `/api/v1/warehouse/stock/{material_id}` | Saldo materiale |
| GET | `/api/v1/warehouse/magazzino` | Vista consolidata magazzino |
| POST | `/api/v1/warehouse/receipts/{id}/certificates` | Upload certificato PDF |
| GET | `/api/v1/warehouse/receipts/{id}/certificates` | Lista certificati DDT |
| GET | `/api/v1/warehouse/receipts/certificates/{cert_id}/download` | Download certificato |

### Distinta base

| Metodo | Path | Descrizione |
|---|---|---|
| POST | `/api/v1/warehouse/distinta/import` | Import file `.xlsx`/`.xlsm`/`.xls`; `?generate_qr=true` genera QR |
| GET | `/api/v1/warehouse/distinta/imports` | Lista importazioni |
| GET | `/api/v1/warehouse/distinta/imports/{id}` | Dettaglio importazione |
| POST | `/api/v1/warehouse/distinta/imports/{id}/generate-qr` | Genera/rigenera QR per tutti i pezzi; `?commessa_id=` arricchisce payload |
| PATCH | `/api/v1/warehouse/distinta/items/{id}` | Aggiorna campi pezzo (part_number, description, quantity, ecc.) |
| POST | `/api/v1/warehouse/distinta/imports/{id}/delta` | Aggiornamento delta (non ancora implementato — 501) |
| GET | `/api/v1/warehouse/distinta/items/{id}/label.pdf` | Etichetta PDF A6 con QR |

### Commesse

| Metodo | Path | Descrizione |
|---|---|---|
| POST | `/api/v1/commesse` | Crea commessa |
| GET | `/api/v1/commesse` | Lista commesse (`?status=`, `?q=`) |
| GET | `/api/v1/commesse/{id}` | Dettaglio commessa |
| PATCH | `/api/v1/commesse/{id}` | Aggiorna commessa |
| DELETE | `/api/v1/commesse/{id}` | Elimina commessa |
| POST | `/api/v1/commesse/{id}/fasi/import` | Import fasi operative da `.xlsx` |
| GET | `/api/v1/commesse/{id}/fasi` | Lista fasi operative |
| PATCH | `/api/v1/commesse/{id}/fasi/{fase_id}` | Aggiorna fase (status, postazione, tempi, note, dipende_da) |

### Stock / Disponibilità

| Metodo | Path | Descrizione |
|---|---|---|
| POST | `/api/v1/stock/analyze` | Analisi disponibilità per lista pezzi |
| POST | `/api/v1/stock/reservations` | Crea prenotazione materiale |
| GET | `/api/v1/stock/requests` | Lista richieste prelievo |
| POST | `/api/v1/stock/requests` | Crea richiesta prelievo |
| POST | `/api/v1/stock/requests/{id}/confirm` | Conferma prelievo |
| POST | `/api/v1/stock/requests/{id}/refuse` | Rifiuta prelievo |

### QR

| Metodo | Path | Descrizione |
|---|---|---|
| POST | `/api/v1/qr/scan` | Decodifica payload QR → dati pezzo |
| GET | `/api/v1/qr/item/{item_id}` | Accesso diretto pezzo per ID |

### Inventario

| Metodo | Path | Descrizione |
|---|---|---|
| POST | `/api/v1/inventario/import` | Import inventario da file |

### Admin

| Metodo | Path | Descrizione |
|---|---|---|
| POST/GET | `/api/v1/admin/users` | Crea/lista utenti |
| GET/PATCH/DELETE | `/api/v1/admin/users/{id}` | Utente singolo |
| GET | `/api/v1/admin/system/status` | Stato sistema |
| GET | `/api/v1/admin/logs` | Log applicazione |
| POST | `/api/v1/admin/maintenance/*` | Operazioni di manutenzione |

## Payload QR

Il QR di ogni pezzo codifica un JSON con i seguenti campi:

```json
{
  "item_id": 42,
  "part_number": "101A",
  "profilo": "HEA 200",
  "commessa": "MCC-2553",
  "fase": "Taglio",
  "postazione": "Stazione 1",
  "sequenza": 3
}
```

Il join tra distinta e fasi operative avviene su `DistintaItem.part_number ↔ FaseOperativa.marca_pos`.

## Formato file Fasi Operative

File `.xlsx` con intestazione alla **riga 4**, dati dalla riga 5.

| Colonna (0-based) | Campo | Tipo |
|---|---|---|
| 0 | Marca/Pos. | testo |
| 1 | Profilo | testo |
| 2 | Q.tà | numero |
| 3 | Fase | testo (obbligatorio) |
| 4 | Postazione | testo |
| 5 | Tempo prev. (min/pz) | numero |
| 6 | Tempo tot. (min) | numero |
| 7 | Sequenza | intero |
| 8 | Dipende da | testo |
| 9 | Note operative | testo |

## Enumerazioni

**CommessaStatus:** `APERTA` · `SOSPESA` · `CHIUSA`

**FaseStatus:** `DA_INIZIARE` · `IN_CORSO` · `COMPLETATA`

**ProfiloUtente:** `Admin` · `Responsabile` · `Operaio` · `Logistica` · `Acquisti`

## Avvio locale

```bash
# 1. Clona e crea venv
python3 -m venv venv
. venv/bin/activate

# 2. Dipendenze
pip install -r requirements.txt

# 3. Avvia
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Swagger UI disponibile su `http://127.0.0.1:8000/docs`.

## Avvio con Docker

```bash
docker compose up --build
```

App disponibile su `http://127.0.0.1:8000`.

## Migrazioni Alembic

```bash
# Crea nuova migrazione
alembic revision --autogenerate -m "descrizione"

# Applica migrazioni
alembic upgrade head

# Rollback di uno step
alembic downgrade -1
```

## Moduli WIP

| Modulo | Stato | Note |
|---|---|---|
| F2 Officina (kanban fasi) | In sviluppo | Scan QR operaio, avanzamento fasi |
| F5 Acquisti (ordini) | Pianificato | Richieste d'acquisto, tracking ordini |
| Delta parser distinta | Stub (501) | Aggiornamento parziale senza reimport completo |
