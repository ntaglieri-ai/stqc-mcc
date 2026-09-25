"""Scanner URLs for the Wi-Fi HTTPS gateway and public deployment."""
import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

LOCAL_ORIGIN_FILE = Path(__file__).resolve().parents[3] / '.venv' / 'local-https' / 'origin.txt'


def scanner_origin(page_origin, local_file=LOCAL_ORIGIN_FILE):
    page = urlsplit(page_origin)
    host = page.hostname or ''
    local = host in {'localhost', 'localhost.localdomain'} or host.endswith('.local')
    try:
        local = local or ipaddress.ip_address(host).is_private
    except ValueError:
        pass
    if not local:
        return 'https://' + page.netloc
    if local_file.exists():
        configured = urlsplit(local_file.read_text(encoding='utf-8').strip())
        if configured.scheme == 'https' and configured.hostname and configured.hostname not in {'localhost', '127.0.0.1', '::1'}:
            return 'https://' + configured.netloc
    if page.scheme == 'https' and host not in {'localhost', '127.0.0.1', '::1'}:
        return 'https://' + page.netloc
    raise ValueError('Avvia HTTPS locale per generare un link utilizzabile dal telefono.')
