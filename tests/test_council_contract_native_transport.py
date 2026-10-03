"""TEST_036 native loopback HTTP/TLS/proxy transport evidence.

No fallback: unavailable sockets/cert tool produce a prerequisite skip.
OpenRouter's fixed URL is redirected locally at session.post, retaining
its real encoding/provider and mounted transport; Ollama uses its real URL.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.client import HTTPConnection
from urllib.parse import urlsplit
import json
import select
import shutil
import socket
import ssl
import subprocess
import threading

import pytest
from urllib3.util.retry import Retry
from app.council_lifecycle import HandoverGate, bind_handover_gate, gated_session
from app.openrouter_llm_provider import OpenRouterLLMProvider
from app.ollama_adapter import OllamaAdapter


@pytest.fixture
def native_socket():
    try:
        with socket.socket() as probe: probe.bind(('127.0.0.1', 0))
    except PermissionError as exc:
        pytest.skip('native loopback prerequisite denied: ' + str(exc))


@pytest.fixture
def tls_context(native_socket, tmp_path):
    executable = shutil.which('openssl')
    if not executable: pytest.skip('native TLS prerequisite missing: openssl')
    key, cert = tmp_path / 'key.pem', tmp_path / 'cert.pem'
    subprocess.run([executable, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                    '-keyout', str(key), '-out', str(cert), '-days', '1',
                    '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1'],
                   check=True, capture_output=True, timeout=10)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return context, str(cert)


@contextmanager
def server(handler, context=None):
    service = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    if context: service.socket = context.wrap_socket(service.socket, server_side=True)
    owner = threading.Thread(target=service.serve_forever, daemon=True)
    owner.start()
    try: yield service
    finally:
        service.shutdown()
        service.server_close()
        owner.join(3)
        assert not owner.is_alive()


@pytest.mark.parametrize('provider_kind', ['openrouter', 'ollama'])
@pytest.mark.parametrize('route', ['http', 'tls', 'http-proxy', 'tls-connect', 'https-proxy'])
def test_supported_binding_boundary_retries_and_closure(native_socket, tls_context, provider_kind, route):
    attempts, observed = [], []
    context, cert = tls_context
    class Receiver(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            attempts.append(self.path)
            observed.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            # First response exercises automatic status retry inside urllib3.
            body = json.dumps({'choices': [{'message': {'content': '{}'}}], 'response': '{}'}).encode()
            self.send_response(503 if len(attempts) == 1 else 200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    class Proxy(Receiver):
        def do_POST(self):
            # The real synthetic provider, not the proxy, observes acceptance.
            body = self.rfile.read(int(self.headers['Content-Length']))
            connection = HTTPConnection('127.0.0.1', upstream.server_port, timeout=2)
            try:
                connection.request('POST', urlsplit(self.path).path or '/', body,
                                   {'Content-Type': 'application/json'})
                response = connection.getresponse()
                content = response.read()
                self.send_response(response.status)
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            finally: connection.close()
        def do_CONNECT(self):
            # Synthetic proxy tunnel restricted to this fixture's loopback.
            target = socket.create_connection(('127.0.0.1', upstream.server_port), timeout=2)
            self.send_response(200)
            self.end_headers()
            try:
                while True:
                    readable, _, _ = select.select([self.connection, target], [], [], 2)
                    if not readable: break
                    for source in readable:
                        data = source.recv(65536)
                        if not data: return
                        (target if source is self.connection else self.connection).sendall(data)
            finally: target.close()
    closed = threading.Event()
    lock = threading.Lock()
    gate = HandoverGate(lock, closed.is_set, 2)
    with server(Receiver, context if route in ('tls', 'tls-connect') else None) as upstream:
        with server(Proxy, context if route == 'https-proxy' else None) as proxy:
            url = ('https' if route in ('tls', 'tls-connect') else 'http') + '://127.0.0.1:' + str(upstream.server_port)
            provider = (OpenRouterLLMProvider(api_key='synthetic-local-only', timeout=2)
                        if provider_kind == 'openrouter' else OllamaAdapter(url=url))
            assert bind_handover_gate(provider, gate, .1)
            session = provider._session if provider_kind == 'openrouter' else provider._client.session
            session.trust_env = False
            session.verify = cert
            if 'proxy' in route or route == 'tls-connect':
                endpoint = ('https' if route == 'https-proxy' else 'http') + '://127.0.0.1:' + str(proxy.server_port)
                session.proxies = {'http': endpoint, 'https': endpoint}
            for adapter in session.adapters.values():
                adapter.max_retries = Retry(total=2, status=2, status_forcelist=[503], allowed_methods={'POST'})
            if provider_kind == 'openrouter':
                original = session.post
                session.post = lambda ignored_url, **kwargs: original(url + '/completion', **kwargs)
            try:
                assert provider.complete('synthetic payload') == '{}'
                assert len(attempts) == gate.summary()['handovers'] == 2
                assert gate.summary()['remote_confirmed'] == 1, '503 rejection must not confirm provider acceptance'
                with lock: closed.set()
                with pytest.raises(Exception): provider.complete('forbidden after closure')
                assert len(attempts) == 2 and gate.summary()['refused_after_close'] >= 1
                assert all('synthetic payload' in json.dumps(body) for body in observed)
            finally: session.close()


def test_native_preboundary_closure_sends_no_request(native_socket, monkeypatch):
    """Connection setup can finish after closure; request bytes cannot."""
    import urllib3.connection
    reached, release, closed = threading.Event(), threading.Event(), threading.Event()
    seen, errors = [], []
    class Receiver(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self): seen.append(self.path)
    original = urllib3.connection.HTTPConnection.connect
    def delayed(self):
        original(self)
        reached.set()
        assert release.wait(2)
    monkeypatch.setattr(urllib3.connection.HTTPConnection, 'connect', delayed)
    gate = HandoverGate(threading.Lock(), closed.is_set, 2)
    session = gated_session(gate, .1)
    session.trust_env = False
    with server(Receiver) as receiver:
        def request():
            try: session.post('http://127.0.0.1:' + str(receiver.server_port), data=b'payload', timeout=1)
            except Exception as error: errors.append(error)
        worker = threading.Thread(target=request)
        try:
            worker.start()
            assert reached.wait(1)
            with gate._lock: closed.set()
            release.set()
            worker.join(3)
            assert not worker.is_alive() and errors
            assert seen == [] and gate.summary()['handovers'] == 0
        finally:
            release.set()
            worker.join(3)
            session.close()
