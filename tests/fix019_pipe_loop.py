"""Opt-in Linux asyncio wakeup SURROGATE for socket-denied verification.

Invoke with PYTEST_PLUGINS=tests.fix019_pipe_loop. This replaces only the
event loop's internal wakeup socketpair with a nonblocking OS pipe. It
does not enable network sockets or substitute product/provider behavior.
ASGI results obtained this way are supplementary, never native gate proof.
The environment variable propagates the explicit surrogate to child pytest
processes. No automatic fallback is installed by ordinary test collection.
"""
import asyncio
import os


class _PipeEnd:
    def __init__(self, fd):
        self.fd = fd
    def fileno(self):
        return self.fd
    def setblocking(self, value):
        os.set_blocking(self.fd, value)
    def recv(self, size):
        return os.read(self.fd, size)
    def send(self, data):
        return os.write(self.fd, data)
    def close(self):
        os.close(self.fd)


def _make_pipe(self):
    read_fd, write_fd = os.pipe()
    self._ssock, self._csock = _PipeEnd(read_fd), _PipeEnd(write_fd)
    self._ssock.setblocking(False)
    self._csock.setblocking(False)
    self._internal_fds += 1
    self._add_reader(self._ssock.fileno(), self._read_from_self)


def pytest_configure(config):
    config._fix019_original_wakeup = asyncio.selector_events.BaseSelectorEventLoop._make_self_pipe
    asyncio.selector_events.BaseSelectorEventLoop._make_self_pipe = _make_pipe


def pytest_unconfigure(config):
    asyncio.selector_events.BaseSelectorEventLoop._make_self_pipe = config._fix019_original_wakeup


def pytest_report_header(config):
    return 'FIX019 SURROGATE: asyncio wakeup uses an OS pipe; no native ASGI/gate claim'
