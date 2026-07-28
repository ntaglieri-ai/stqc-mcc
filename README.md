# STQC-MCC

Sistema di Tracciamento QR su Commessa per MCC S.r.l.

Gestionale operativo per carpenteria metallica pesante, con tracciamento QR dei materiali di magazzino e dei singoli pezzi di commessa lungo l'intero ciclo produttivo — dal magazzino, alla produzione in officina, alle lavorazioni esterne, fino alla spedizione in cantiere.

**Il sistema è operativo in produzione presso MCC** (`https://stqc.stqcmcc.it`), on-premise con tunnel Cloudflare.

## Stato Attuale

| Area | Stato | Note |
| --- | --- | --- |
| Home direzionale | Implementata | "Vista Direttore" con moduli dashboard, commesse e magazzino in colonna. Dashboard con KPI reali ancora da popolare. |
| Magazzino | Implementato / in evoluzione | Inventario, movimenti, QR per singolo elemento fisico, stampa etichette, filtri, DDT. |
| Analisi commessa | Implementata fino a Step 5.1 | Import file commessa, riepilogo, classificazione pezzi, generazione DB pezzi e QR commessa. |
| DDT magazzino | Implementato come workflow preliminare | Parsing PDF, proposta materiali, review editabile, conferma manuale, creazione QR magazzino. |
| Produzione/officina | **Implementato** | Scan via HTTP (scanner NETUM DS2800), postazioni, tracking pezzo per pezzo. |
| Post-officina | **Implementato** | Lavorazioni esterne e "in cantiere" con logica start/end su fasi dedicate. |
| Certificati EN 10204 | Implementato | Endpoint dedicato per gestione certificati materiali. |
| Dashboard KPI | Da popolare | Struttura pronta, dati reali da collegare. |

## Principio Architetturale

Il progetto separa volutamente:

1. Magazzino
2. Commessa
3. Link tra commessa e magazzino

Il magazzino non è trattato come parte della commessa. Il collegamento tra pezzi richiesti dalla distinta e materiale fisico disponibile resta uno step progettato con criteri industriali specifici per travi, lamiere, tubi e profili pesanti — non automatizzato, non distruttivo.

## Due Famiglie Di QR

### QR Magazzino

Ogni elemento fisico presente in magazzino ha un QR univoco (es. `LAMIERA-1-ZINCATO-#0001`), che rimanda a un `WarehouseItem`. Creati durante: import inventario, ingresso manuale, conferma DDT, riconciliazioni.

### QR Commessa

Ogni singolo pezzo fisico di commessa ha un QR univoco, generato dal file "Lavorazioni per Posizione". Esempio: `Marca/Pos = 2604B127, Q.ta = 16` genera `2604B127-001` ... `2604B127-016`. Il QR contiene solo il codice del pezzo, non un JSON complesso.

## Flusso Magazzino

La pagina `/magazzino` include: sidebar tipologie, filtro globale, filtri per colonna, tabella materiali, evidenza record associati a commesse/movimenti, espansione QR per singoli elementi fisici, anteprima QR ingrandita, stampa singola/multipla etichetta, ingresso/uscita materiale, import inventario, analisi DDT.

### Endpoint QR Magazzino Ed Etichette

| Metodo | Path | Descrizione |
| --- | --- | --- |
| GET | `/api/v1/warehouse/materials/{material_id}/items` | Lista elementi fisici di un materiale |
| GET | `/api/v1/warehouse/items/{item_uuid}/qr.png` | PNG QR singolo elemento |
| GET | `/api/v1/warehouse/items/{item_uuid}/label.pdf` | Etichetta PDF singola |
| GET | `/api/v1/warehouse/materials/{material_id}/labels.pdf` | Etichette PDF per tutti gli elementi |
| POST | `/api/v1/warehouse/items/scan` | Risolve un QR magazzino |

## Analisi DDT

Sottomodulo del magazzino. Flusso: upload PDF/scansione → parser estrae fornitore/numero/data/materiali → proposta ingresso → review popup editabile → conferma manuale crea movimento/materiale/elementi fisici QR.

File: `backend/app/services/ddt.py`, `backend/app/api/api_v1/endpoints/inventario.py`, `backend/app/static/magazzino.html`

Endpoint: `POST /api/v1/inventario/ddt/analyze`, `POST /api/v1/inventario/ddt/confirm`

## Analisi Commessa

| Step | Stato | Descrizione |
| --- | --- | --- |
| Step 4 | Implementato | Lettura lista pezzi, riepilogo, classificazione materiali, anomalie tecniche |
| Step 5.1 | Implementato | Generazione DB dei singoli pezzi fisici e QR commessa |
| Step 5.2+ | Da progettare | Analisi magazzino, proposta sfridi/residui, piani operativi |

Concetti: "Pezzi fisici" = quantità totale da produrre; "Marca/Pos" = codice posizione/pezzo base in distinta; riga con quantità > 1 genera più pezzi fisici e QR.

## Produzione, Scan E Post-Officina

### Officina (implementato)

Scan del pezzo tramite scanner fisico **NETUM DS2800 in modalità HTTP** (non TCP/IP): lo scanner invia una richiesta POST con `device_token` che identifica univocamente la postazione/scanner.

Endpoint pubblici (nessun JWT — lo scanner non fa login):

| Metodo | Path | Descrizione |
| --- | --- | --- |
| POST | `/api/v1/scanner/netum/{device_token}/scan` | Registra uno scan pezzo |
| POST | `/api/v1/scanner/netum/{device_token}/preproduction-scan` | Scan pre-produzione |
| POST | `/api/v1/scanner/netum/{device_token}/read` | Lettura scan grezza |
| GET | `/api/v1/scanner/netum/{device_token}/latest-read` | Ultimo scan registrato per il device |

Endpoint gestione officina (autenticati):

| Metodo | Path | Descrizione |
| --- | --- | --- |
| GET | `/api/v1/officina/commesse` | Lista commesse in produzione |
| GET | `/api/v1/officina/{commessa_id}/postazioni` | Postazioni attive per commessa |
| GET | `/api/v1/officina/{commessa_id}/postazioni/{postazione}/pezzi` | Pezzi per postazione |
| POST | `/api/v1/officina/scan` | Scan manuale/gestionale |

### Post-Officina: lavorazioni esterne e spedizione (implementato)

Ogni fase successiva all'officina segue lo stesso principio **START/END** già usato per le postazioni interne: scan pezzo → scan QR fase-START → scan QR fase-END. Applicato a lavorazioni esterne (es. zincatura, verniciatura) e spedizione in cantiere.

Tabella dati: `pezzo_percorso` (vincolo univoco su `commessa_id`, `marca_pos`, `instance_number`, `fase_id`) — registra ogni tappa del percorso del pezzo, interna o esterna, in ordine cronologico. Nessuna logica di validazione automatica delle sequenze: solo registrazione.

Pagine: `/commesse/{ref}/lavorazioni`, `/commesse/{ref}/in-cantiere`

### Tabelle correlate (modello dati)

`pieces`, `workstations`, `scanner_devices`, `work_types`, `piece_scan_events`, `piece_work_sessions`, `workshop_scan_blocks`, `workshop_scan_attempts`, `scanner_read_states`, `fasi_operative`, `commessa_post_officina_items`

## Mapping Assemblati

Il file "Lista Parti Assemblaggi" collega marche/posizioni agli assemblati padre. Avanzamento assemblato = pezzi completati / pezzi previsti.

## Link Futuro Tra Commessa E Magazzino

Non finalizzato. La commessa genera i suoi pezzi/QR; il magazzino gestisce i suoi elementi fisici/QR separatamente; l'analisi magazzino resta un passaggio separato, non automatico, non distruttivo.

## Certificati EN 10204

Endpoint dedicato alla gestione dei certificati di conformità materiali.

| Metodo | Path | Descrizione |
| --- | --- | --- |
| (vedi `certificates.py`) | `/api/v1/warehouse/receipts/*` | Gestione certificati EN 10204 |

## API Reference Principale

### Autenticazione

| Metodo | Path | Descrizione |
| --- | --- | --- |
| POST | `/api/v1/auth/login` | Login username/password |
| POST | `/api/v1/auth/login-pin` | Login con PIN |
| GET | `/api/v1/auth/me` | Utente autenticato |

### Magazzino

| Metodo | Path | Descrizione |
| --- | --- | --- |
| GET | `/api/v1/warehouse/magazzino` | Vista consolidata magazzino |
| POST/GET | `/api/v1/warehouse/materials` | Materiali |
| GET/PATCH/DELETE | `/api/v1/warehouse/materials/{id}` | Materiale singolo |
| POST/GET | `/api/v1/warehouse/movements` | Movimenti stock |
| GET | `/api/v1/warehouse/stock/{material_id}` | Saldo materiale |

### Inventario E DDT

| Metodo | Path | Descrizione |
| --- | --- | --- |
| POST | `/api/v1/inventario/import` | Import inventario da Excel |
| POST | `/api/v1/inventario/ddt/analyze` | Analisi DDT |
| POST | `/api/v1/inventario/ddt/confirm` | Conferma DDT in magazzino |

### Commesse

| Metodo | Path | Descrizione |
| --- | --- | --- |
| POST | `/api/v1/commesse` | Crea commessa |
| GET | `/api/v1/commesse` | Lista commesse |
| GET/PATCH/DELETE | `/api/v1/commesse/{id}` | Dettaglio, modifica, cancellazione |
| POST | `/api/v1/commesse/{id}/analisi` | Import/analisi file commessa |
| POST | `/api/v1/commesse/{id}/step-5-1` | Genera DB pezzi e QR commessa |
| GET | `/api/v1/commesse/{id}/step-5-1/items` | Lista pezzi generati |

### Scanner (pubblico, nessun JWT)

| Metodo | Path | Descrizione |
| --- | --- | --- |
| POST | `/api/v1/scanner/netum/{device_token}/scan` | Scan pezzo |
| POST | `/api/v1/scanner/netum/{device_token}/preproduction-scan` | Scan pre-produzione |
| GET | `/api/v1/scanner/netum/{device_token}/latest-read` | Ultimo scan |

### Officina

| Metodo | Path | Descrizione |
| --- | --- | --- |
| GET | `/api/v1/officina/commesse` | Commesse in produzione |
| GET | `/api/v1/officina/{commessa_id}/postazioni` | Postazioni per commessa |
| POST | `/api/v1/officina/scan` | Scan gestionale |

### Stock (disattivato)

Endpoint `/api/v1/stock/*` disattivati con `410 Gone`. La vecchia logica mescolava magazzino e commessa.

## Pagine Frontend

| Path | Pagina |
| --- | --- |
| `/login` | Login |
| `/` | Home direzionale |
| `/dashboard` | Dashboard (alias lista commesse, KPI da popolare) |
| `/magazzino` | Magazzino |
| `/commesse` | Lista commesse |
| `/commesse/nuova` | Nuova commessa |
| `/commesse/{ref}/analisi` | Analisi commessa |
| `/commesse/{ref}/officina` | Officina per commessa |
| `/commesse/{ref}/assemblaggi` | Assemblaggi |
| `/commesse/{ref}/lavorazioni` | Lavorazioni esterne |
| `/commesse/{ref}/in-cantiere` | In cantiere / spedizione |
| `/commesse/{ref}/qr-registry` | Registro QR commessa |
| `/commesse/{ref}` | Dettaglio commessa |
| `/p/{item_uuid}` | Risoluzione QR magazzino |
| `/officina` | Modulo officina generale |
| `/scanner-view/{device_token}` | Vista scanner per device |
| `/admin` | Admin |

## Stack Tecnico

| Layer | Tecnologia |
| --- | --- |
| Backend | Python + FastAPI |
| ORM | SQLAlchemy 2.x |
| Database | SQLite |
| Migrazioni | Alembic |
| Autenticazione | JWT |
| Frontend | HTML statico + Vanilla JS |
| QR | `qrcode`, PNG/PDF labels |
| Excel | `openpyxl`, `xlrd` |
| PDF/DDT | `pdfplumber`, `pypdf`, OCR opzionale con Tesseract |
| Scanner | NETUM DS2800, protocollo HTTP |
| Deploy produzione | On-premise Windows, Task Scheduler, Cloudflare Tunnel |
| Deploy locale/alternativo | Docker Compose |

## Avvio Locale

```
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

App: `http://127.0.0.1:8000` — Swagger: `http://127.0.0.1:8000/docs`

## Migrazioni Alembic

```
alembic revision --autogenerate -m "descrizione"
alembic upgrade head
alembic downgrade -1
```

## Deploy Produzione (MCC)

Ambiente on-premise Windows presso MCC, accesso pubblico via Cloudflare Tunnel (`https://stqc.stqcmcc.it`). App e tunnel avviati automaticamente via Windows Task Scheduler. Manutenzione remota tramite Tailscale + RDP.

## Prossimi Step

1. Popolare Dashboard con KPI reali (magazzino, commesse, produzione).
2. Fix UI: layout responsive (zoom), colore testo (bianco pieno), sensibilità scroll e visibilità scrollbar.
3. Cambio credenziali produzione (rimuovere `admin`/`admin`).
4. Rimozione `JWT_SECRET` hardcoded da `config.py`.
5. Rotazione log applicativi.
6. Concordare con MCC gestione operativa lavorazioni esterne (elenco fornitori, QR fissi dedicati).
7. Step 5.2: analisi magazzino riprogettata.
8. User manual per profilo utente.

## Note Operative

- Il sistema è operativo in produzione presso MCC.
- Il magazzino e il modulo commessa restano separati finché il link tecnico non sarà progettato.
- Qualsiasi import/parsing produce una proposta editabile prima di creare dati definitivi.
- Nessuna logica di analisi/matching complessa viene aggiunta al sistema senza esplicita richiesta: solo azioni semplici, confronti diretti, gestione quantità.
