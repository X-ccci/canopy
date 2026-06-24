"""
轻量 Prometheus Metrics HTTP 服务器 — 纯标准库，端口 9090。

启动方式：
    python -m canopy.utils.metrics_server
    # 或
    from canopy.utils.metrics_server import start_metrics_server
    start_metrics_server(port=9090)
"""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from canopy.utils.metrics import collect_all


class _MetricsHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/metrics":
            body = collect_all().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress default stderr logging


def start_metrics_server(port: int = 9090, daemon: bool = True) -> HTTPServer:
    """启动指标 HTTP 服务器，默认守护线程运行。"""
    server = HTTPServer(("0.0.0.0", port), _MetricsHandler)
    t = threading.Thread(target=server.serve_forever, daemon=daemon, name="metrics-http")
    t.start()
    return server


if __name__ == "__main__":
    print("[metrics] Prometheus metrics server starting on :9090")
    start_metrics_server(daemon=False)
    import time
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n[metrics] shutting down")
