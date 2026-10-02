"""Reserve a local listener before startup, without probing and releasing the port."""

import errno
import socket

DEFAULT_GATEWAY_PORT = 8087


def bind_listener(host: str, port: int, *, fallback_step: int | None = None) -> socket.socket:
    while port <= 65535:
        listener = socket.socket(
            socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM
        )
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((host, port))
            listener.listen(128)
            return listener
        except OSError as exc:
            listener.close()
            if exc.errno != errno.EADDRINUSE or fallback_step is None:
                raise
            port += fallback_step
    raise OSError(errno.EADDRINUSE, "No available port in the gateway fallback sequence")
