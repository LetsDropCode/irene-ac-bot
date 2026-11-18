"""Test-process guard loaded via PYTHONPATH; production never imports this.

Mock the HTTP boundary above Session.send in tests. Any accidental real
requests-based HTTP (including Meta and scripts) fails before opening a socket.
"""

import requests.sessions


def _deny_http(self, request, **kwargs):
    raise AssertionError("Real HTTP is disabled during offline tests; mock the transport")


requests.sessions.Session.send = _deny_http
