"""Local Wi-Fi HTTPS gateway. Run with the PC's LAN IPv4 address."""
import argparse
import http.client
import ipaddress
import ssl
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

ROOT = Path(__file__).resolve().parents[1]
CERTS = ROOT / '.venv' / 'local-https'
HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade'}


def certificates(address):
    CERTS.mkdir(parents=True, exist_ok=True)
    ca_path = CERTS / 'mcc-local-ca.pem'
    if ca_path.exists():
        if (CERTS / 'address.txt').read_text() != address:
            raise RuntimeError('LAN address changed; regenerate certificates explicitly.')
        return
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'MCC Locale Wi-Fi')])
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=365))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, address)]))
              .issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=90))
              .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
              .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(address))]), critical=False)
              .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
              .add_extension(x509.KeyUsage(True, False, True, False, False, False, False, False, False), critical=True)
              .sign(ca_key, hashes.SHA256()))
    # The CA signing key is intentionally never saved.
    (CERTS / 'server.key').write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (CERTS / 'server.pem').write_bytes(server.public_bytes(serialization.Encoding.PEM))
    (CERTS / 'mcc-local-ca.cer').write_bytes(ca.public_bytes(serialization.Encoding.DER))
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (CERTS / 'address.txt').write_text(address)


class QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Scanner URLs contain device credentials.


class CertificateDownload(QuietHandler):
    def do_GET(self):
        if self.path not in ('/', '/mcc-local-ca.cer'):
            self.send_error(404)
            return
        body = (CERTS / 'mcc-local-ca.cer').read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-x509-ca-cert')
        self.send_header('Content-Disposition', 'attachment; filename="mcc-local-ca.cer"')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Gateway(QuietHandler):
    def proxy(self):
        if self.headers.get('Transfer-Encoding'):
            self.send_error(501, 'Chunked request bodies are not supported')
            return
        upstream = http.client.HTTPConnection('127.0.0.1', 8000, timeout=120)
        try:
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS}
            headers['X-Forwarded-Proto'] = 'https'
            headers['X-Forwarded-For'] = self.client_address[0]
            upstream.request(self.command, self.path, body=body, headers=headers)
            response = upstream.getresponse()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in HOP_HEADERS:
                    self.send_header(key, value)
            self.end_headers()
            if self.command != 'HEAD':
                while chunk := response.read(65536):
                    self.wfile.write(chunk)
        except (ConnectionError, TimeoutError, OSError):
            self.close_connection = True
        finally:
            upstream.close()

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = proxy


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('address', type=str)
    args = parser.parse_args()
    ipaddress.IPv4Address(args.address)
    certificates(args.address)
    download = ThreadingHTTPServer((args.address, 8444), CertificateDownload)
    gateway = ThreadingHTTPServer((args.address, 8443), Gateway)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(CERTS / 'server.pem', CERTS / 'server.key')
    gateway.socket = tls.wrap_socket(gateway.socket, server_side=True)
    (CERTS / 'origin.txt').write_text(f'https://{args.address}:8443', encoding='utf-8')
    threading.Thread(target=download.serve_forever, daemon=True).start()
    print(f'HTTPS ready: https://{args.address}:8443', flush=True)
    gateway.serve_forever()
