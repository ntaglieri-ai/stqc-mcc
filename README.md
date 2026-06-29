# STQC-MCC

Sistema di Tracciamento QR su Commessa per MCC S.r.l.

Il progetto e in sviluppo. L'obiettivo e costruire un gestionale operativo per carpenteria metallica pesante, con tracciamento QR dei materiali di magazzino e dei singoli pezzi di commessa lungo il ciclo produttivo.

## Stato Attuale

Il lavoro recente ha consolidato quattro aree principali:

| Area | Stato | Note |
|---|---:|---|
| Home direzionale | Implementata | Vista "Vista Direttore" con moduli dashboard, commesse e magazzino in colonna premium. |
| Magazzino | Implementato / in evoluzione | Inventario, movimenti, QR per singolo elemento fisico, stampa etichette, filtri e DDT. |
| Analisi commessa | Implementata fino a Step 5.1 | Import file commessa, riepilogo, classificazione pezzi, generazione DB pezzi e QR commessa. |
| DDT magazzino | Implementato come workflow preliminare | Parsing PDF, proposta materiali, review editabile, conferma manuale e creazione QR magazzino. |
| Produzione/officina | Base presente | Postazioni e scan in bozza, ancora da validare sul flusso operativo reale. |

## Principio Architetturale

Il progetto separa volutamente:

1. Magazzino
2. Commessa
3. Futuro link tra commessa e magazzino

Il magazzino non deve essere trattato come parte della commessa. Il link tra pezzi richiesti dalla distinta e materiale fisico disponibile sara uno step successivo, da progettare con criteri industriali corretti per travi, lamiere, tubi e profili pesanti.

## Due Famiglie Di QR

### QR Magazzino

Ogni elemento fisico presente in magazzino ha un QR univoco.

Esempio:

```text
LAMIERA-1-ZINCATO-#0001
```

Il QR rimanda a un `WarehouseItem`, cioe un singolo elemento fisico collegato a un materiale di magazzino.

I QR magazzino vengono creati:

- durante import inventario;
- durante ingresso manuale;
- durante conferma DDT;
- durante riconciliazioni che generano nuovi elementi fisici.

Ogni record raggruppato in tabella puo essere espanso per vedere tutti gli elementi fisici e i relativi QR.

### QR Commessa

Ogni singolo pezzo fisico di commessa ha un QR univoco.

La sorgente e il file "Lavorazioni per Posizione".

Esempio:

```text
Marca/Pos = 2604B127
Q.ta = 16
```

Genera:

```text
2604B127-001
2604B127-002
2604B127-003
...
2604B127-016
```

Il QR contiene il codice del singolo pezzo, non un JSON complesso.

## Flusso Magazzino

La pagina `/magazzino` include:

- sidebar tipologie;
- filtro globale;
- filtri per colonna con liste a tendina;
- tabella materiali;
- evidenza record associati a commesse o movimenti;
- espansione QR per singoli elementi fisici;
- anteprima QR ingrandita;
- stampa singola etichetta;
- stampa tutte le etichette di un record;
- formato etichetta configurabile;
- ingresso e uscita materiale;
- import inventario;
- analisi DDT.

### QR Magazzino Ed Etichette

Gli endpoint principali sono:

| Metodo | Path | Descrizione |
|---|---|---|
| GET | `/api/v1/warehouse/materials/{material_id}/items` | Lista elementi fisici di un materiale |
| GET | `/api/v1/warehouse/items/{item_uuid}/qr.png` | PNG QR singolo elemento |
| GET | `/api/v1/warehouse/items/{item_uuid}/label.pdf` | Etichetta PDF singola |
| GET | `/api/v1/warehouse/materials/{material_id}/labels.pdf` | Etichette PDF per tutti gli elementi del materiale |
| POST | `/api/v1/warehouse/items/scan` | Risolve un QR magazzino |

## Analisi DDT

Il modulo DDT e un sottomodulo del magazzino.

Flusso:

1. Clic su `Analizza DDT`.
2. Upload PDF o scansione.
3. Parser estrae fornitore, numero DDT, data e materiali.
4. Il sistema mostra una proposta di ingresso.
5. Clic su `Review ingresso`.
6. Si apre un popup centrale sopra il drawer, con drawer sfocato in secondo piano.
7. Tutti i dati sono editabili manualmente.
8. Solo al clic su `Conferma ingresso magazzino` vengono creati movimento, materiale ed elementi fisici QR.

Campi editabili nella review:

- fornitore;
- numero DDT;
- data DDT;
- riferimento interno;
- codice materiale;
- descrizione;
- quantita;
- unita;
- tipo;
- profilo;
- dimensioni;
- qualita;
- colata;
- peso totale;
- peso unitario.

File e parser DDT:

| File | Ruolo |
|---|---|
| `backend/app/services/ddt.py` | Estrazione testo PDF/OCR e parsing DDT |
| `backend/app/api/api_v1/endpoints/inventario.py` | Endpoint analyze/confirm DDT |
| `backend/app/static/magazzino.html` | UI drawer + review DDT |

Endpoint DDT:

| Metodo | Path | Descrizione |
|---|---|---|
| POST | `/api/v1/inventario/ddt/analyze` | Analizza PDF DDT e restituisce una proposta |
| POST | `/api/v1/inventario/ddt/confirm` | Conferma proposta editata e crea ingresso magazzino |

Note:

- Il parser non movimenta nulla da solo.
- La conferma e sempre manuale.
- Alla conferma vengono generati anche i QR degli elementi fisici.
- Tesseract OCR e consigliato per DDT scansionati.

## Flusso Nuova Commessa

La pagina nuova commessa resta una pagina di start:

- dati generali commessa;
- cliente;
- consegna prevista;
- flag `Pre-distinta`;
- caricamento file;
- creazione commessa.

File previsti:

| File | Uso |
|---|---|
| Lavorazioni per Posizione | Sorgente principale dei pezzi e QR commessa |
| Lista Parti Assemblaggi | Mapping pezzo -> assemblato padre |
| Lista Spedizione | Assemblati finali da spedire |

Il flag `Pre-distinta` blocca l'avvio produzione diretto. In caso di distinta definitiva, Step 4 e Step 5 devono poter essere rieseguiti.

## Analisi Commessa

L'analisi commessa legge la distinta e prepara la base dati dei pezzi.

Step consolidati:

| Step | Stato | Descrizione |
|---|---:|---|
| Step 4 | Implementato | Lettura lista pezzi, riepilogo, classificazione materiali, anomalie tecniche essenziali |
| Step 5.1 | Implementato | Generazione DB dei singoli pezzi fisici e QR commessa |
| Step 5.2+ | Da progettare | Analisi magazzino, proposta sfridi/residui, piani operativi |
| Step 5.9 | Da progettare | Avvio produzione, non abilitato se `Pre-distinta` |

Concetto importante:

- "Pezzi fisici" = quantita totale di pezzi da produrre.
- "Marca/Pos" = codice posizione/pezzo base presente in distinta.
- Una riga con quantita > 1 genera piu pezzi fisici e quindi piu QR.

Esempio:

```text
2604B127, q.ta 16
```

diventa:

```text
2604B127-001 ... 2604B127-016
```

## Mapping Assemblati

Il file "Lista Parti Assemblaggi" collega le marche/posizioni agli assemblati padre.

Esempio:

```text
2604B127-001 -> 2604A101
2604B127-002 -> 2604A101
```

L'avanzamento assemblato sara calcolato come:

```text
pezzi completati / pezzi previsti
```

## Produzione E Scan

La logica target per la produzione e:

1. Scan QR pezzo.
2. Scan QR postazione start.
3. Scan QR postazione end.

Esempi postazione:

```text
TAGLIO01_START
TAGLIO01_END
FORATURA01_START
FORATURA01_END
ASS01_START
ASS01_END
```

Ogni scansione dovra generare un evento.

Tabella concettuale:

```text
scan_events
- id
- timestamp
- pezzo_id
- commessa_id
- assemblato_id
- postazione_id
- evento
- operatore_id
```

Questa parte e ancora da completare e testare operativamente con smartphone/tablet o lettore barcode.

## Link Futuro Tra Commessa E Magazzino

Il link non e ancora stato finalizzato.

Decisione attuale:

- la commessa genera i suoi pezzi e QR;
- il magazzino gestisce i suoi elementi fisici e QR;
- l'analisi magazzino sara un passaggio separato, non automatico e non distruttivo;
- eventuale sfrido/residuo sara solo calcolato e proposto, poi confermato dalla logistica.

Tema aperto:

Non esiste ancora un vero part number comune tra distinta e magazzino. Il confronto dovra usare criteri tecnici:

- tipo materiale;
- profilo;
- dimensioni;
- qualita;
- lunghezza/spessore;
- colata/certificato quando rilevante;
- regole di sfrido/residuo.

## API Reference Principale

### Autenticazione

| Metodo | Path | Descrizione |
|---|---|---|
| POST | `/api/v1/auth/login` | Login username/password |
| POST | `/api/v1/auth/login-pin` | Login con PIN |
| GET | `/api/v1/auth/me` | Utente autenticato |

### Magazzino

| Metodo | Path | Descrizione |
|---|---|---|
| GET | `/api/v1/warehouse/magazzino` | Vista consolidata magazzino |
| POST/GET | `/api/v1/warehouse/materials` | Materiali |
| GET/PATCH/DELETE | `/api/v1/warehouse/materials/{id}` | Materiale singolo |
| POST/GET | `/api/v1/warehouse/movements` | Movimenti stock |
| GET | `/api/v1/warehouse/stock/{material_id}` | Saldo materiale |
| DELETE | `/api/v1/warehouse/materials/{material_id}` | Cancella materiale |

### Inventario E DDT

| Metodo | Path | Descrizione |
|---|---|---|
| POST | `/api/v1/inventario/import` | Import inventario da Excel |
| POST | `/api/v1/inventario/ddt/analyze` | Analisi DDT |
| POST | `/api/v1/inventario/ddt/confirm` | Conferma DDT in magazzino |

### Commesse

| Metodo | Path | Descrizione |
|---|---|---|
| POST | `/api/v1/commesse` | Crea commessa |
| GET | `/api/v1/commesse` | Lista commesse |
| GET/PATCH/DELETE | `/api/v1/commesse/{id}` | Dettaglio, modifica, cancellazione |
| POST | `/api/v1/commesse/{id}/analisi` | Import/analisi file commessa |
| GET | `/api/v1/commesse/{id}/analisi` | Stato analisi corrente |
| GET | `/api/v1/commesse/{id}/analisi/materiali` | Materiali classificati della commessa |
| POST | `/api/v1/commesse/{id}/step-5-1` | Genera DB pezzi e QR commessa |
| GET | `/api/v1/commesse/{id}/step-5-1/items` | Lista pezzi generati |
| POST | `/api/v1/commesse/{id}/avvia-produzione` | Avvio produzione, da completare |

### Distinta Legacy

| Metodo | Path | Descrizione |
|---|---|---|
| POST | `/api/v1/warehouse/distinta/import` | Import distinta legacy |
| GET | `/api/v1/warehouse/distinta/imports` | Lista import |
| POST | `/api/v1/warehouse/distinta/imports/{id}/generate-qr` | Generazione QR distinta legacy |

### Stock

Gli endpoint `/api/v1/stock/*` sono stati disattivati con `410 Gone`.

Motivo: la logica vecchia mescolava magazzino e commessa. La nuova analisi magazzino sara riprogettata come Step 5 successivo, separato dalla gestione commessa.

## Pagine Frontend

| Path | Pagina |
|---|---|
| `/login` | Login |
| `/` | Home direzionale |
| `/magazzino` | Magazzino |
| `/commesse` | Lista commesse |
| `/commesse/nuova` | Nuova commessa |
| `/commesse/{id}/analisi` | Analisi commessa |
| `/commesse/{id}` | Dettaglio commessa |
| `/p/{item_uuid}` | Risoluzione QR magazzino |
| `/officina` | Modulo officina |
| `/admin` | Admin |

## Stack Tecnico

| Layer | Tecnologia |
|---|---|
| Backend | Python + FastAPI |
| ORM | SQLAlchemy 2.x |
| Database | SQLite (`backend/app.db`) |
| Migrazioni | Alembic |
| Autenticazione | JWT |
| Frontend | HTML statico + Vanilla JS |
| QR | `qrcode`, PNG/PDF labels |
| Excel | `openpyxl`, `xlrd` |
| PDF/DDT | `pdfplumber`, `pypdf`, OCR opzionale con Tesseract |
| Deploy | Docker Compose |

## Struttura Del Progetto

```text
stqc-mcc/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/api_v1/endpoints/
│   │   │   ├── auth.py
│   │   │   ├── warehouse.py
│   │   │   ├── inventario.py
│   │   │   ├── commessa.py
│   │   │   ├── distinta.py
│   │   │   ├── stock.py
│   │   │   ├── qr.py
│   │   │   ├── officina.py
│   │   │   └── admin.py
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   │   ├── ddt.py
│   │   │   ├── commessa_analysis.py
│   │   │   ├── distinta.py
│   │   │   └── warehouse_items.py
│   │   ├── db/session.py
│   │   └── static/
│   └── app.db
├── alembic/
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

## Avvio Locale

```bash
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

App:

```text
http://127.0.0.1:8000
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

Account di sviluppo:

| Username | Password | Profilo |
|---|---|---|
| `admin` | `admin` | Admin |
| `direttore` | `direttore` | Direttore |
| `progettazione` | `progettazione` | Progettazione |
| `logistica` | `logistica` | Logistica |
| `acquisti` | `acquisti` | Acquisti |

## OCR DDT

Per DDT scansionati o PDF immagine, installare Tesseract.

macOS:

```bash
brew install tesseract tesseract-lang
```

Docker:

```text
Il Dockerfile installa gia tesseract-ocr, tesseract-ocr-ita e tesseract-ocr-eng.
```

Il parser prova prima l'estrazione testo PDF, poi OCR quando necessario.

## Avvio Docker

```bash
docker compose up --build
```

## Migrazioni Alembic

```bash
alembic revision --autogenerate -m "descrizione"
alembic upgrade head
alembic downgrade -1
```

## Backup, Pulizia, Reset

Sono presenti endpoint admin per backup, verifica DB e reset inventario.

Tema ancora da finalizzare:

- politica backup dati;
- pulizia dati demo;
- reset completo per ripartenza da scratch;
- separazione tra dati test e dati operativi.

## Prossimi Step

Priorita ragionata:

1. Pulizia codice legacy non piu coerente con la separazione magazzino/commessa.
2. Test QR reali con smartphone/tablet o lettore barcode.
3. Definizione `scan_events` e logica start/end postazioni.
4. Backup dati e procedura ripristino.
5. Step 5.2: analisi magazzino riprogettata, senza vecchie prenotazioni automatiche.
6. Calcolo sfridi/residui come proposta per logistica, non come movimento automatico.
7. Avvio produzione Step 5.9, bloccato se commessa nata da pre-distinta.

## Note Operative

- Il progetto non e ancora operativo in produzione.
- Le funzioni admin verranno rifinite alla fine.
- Il magazzino e il modulo commessa devono restare separati finche il link tecnico non sara progettato.
- Qualsiasi import/parsing deve produrre una proposta editabile prima di creare dati definitivi.
