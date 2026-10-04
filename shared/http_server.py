"""Threading HTTP server that does not spam journals on client disconnects."""

from __future__ import annotations

import logging
import sys
from http.server import ThreadingHTTPServer

log = logging.getLogger("http")

# Clients (browsers, HA, curl -N) often abort mid-JPEG; that is not a service fault.
_CLIENT_GONE = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Like ThreadingHTTPServer, but quiet for BrokenPipe / ConnectionReset."""

    def handle_error(self, request, client_address) -> None:  # noqa: ANN001
        exc = sys.exc_info()[1]
        if isinstance(exc, _CLIENT_GONE):
            host = client_address[0] if client_address else "?"
            log.debug(
                "client disconnected %s (%s)",
                host,
                type(exc).__name__,
            )
            return
        super().handle_error(request, client_address)
