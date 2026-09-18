# Aggiornamento server MCC

Procedura standard per aggiornare la produzione dal branch `main`.

```bash
ssh stqc@57.131.134.160

cd /opt/stqc-mcc
git pull --ff-only origin main

set -a
source .env
set +a

./venv/bin/alembic upgrade head
sudo systemctl restart stqc-mcc

curl -I https://stqc.stqcmcc.it
```

Se `git pull` segnala modifiche locali o un conflitto, interrompere la procedura
senza forzare o cancellare file e controllare lo stato del repository.

Per verificare il servizio in caso di errore:

```bash
sudo systemctl status stqc-mcc --no-pager -l
```

