"""
RobotHTTPServer: thin wrapper around ThreadingHTTPServer.

daemon_threads = True ensures that open MJPEG /stream handler threads (which sit
in an infinite write loop) are treated as daemon threads and do not block
server.shutdown() from returning.  Without this, a connected stream client holds
a non-daemon thread alive and Ctrl+C hangs forever.
"""

import threading
from http.server import ThreadingHTTPServer


class _DaemonThreadingHTTPServer(ThreadingHTTPServer):
    # Mark every spawned request-handler thread as a daemon so they don't
    # prevent the interpreter from exiting and don't block shutdown().
    daemon_threads = True


class RobotHTTPServer:
    def __init__(self, host: str, port: int, handler_class):
        self._server = _DaemonThreadingHTTPServer((host, port), handler_class)

    def start(self, block: bool = True) -> None:
        if block:
            self._server.serve_forever()
        else:
            t = threading.Thread(target=self._server.serve_forever, daemon=True)
            t.start()

    def stop(self) -> None:
        # shutdown() signals serve_forever() to exit and waits for it.
        # server_close() releases the listening socket.
        # Must be called from a thread OTHER than the serve_forever thread.
        try:
            self._server.shutdown()
        except Exception:
            pass
        try:
            self._server.server_close()
        except Exception:
            pass
