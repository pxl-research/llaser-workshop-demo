"""A pretend attacker's server for the image-leak demo: prints every request that reaches it.

Listens on this laptop only (127.0.0.1). It answers every request with an invisible 1x1 image,
so the chat shows nothing while the data arrives here.

    python3 scripts/leak-listener.py            # port 9911
    python3 scripts/leak-listener.py 9912       # another port

Stop it with Ctrl+C. Needs only Python 3, no packages.
"""
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

# The smallest transparent GIF.
INVISIBLE_GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
)


class LeakListener(BaseHTTPRequestHandler):
    def do_GET(self):
        self.print_request()
        self.send_response(200)
        self.send_header("Content-Type", "image/gif")
        self.send_header("Content-Length", str(len(INVISIBLE_GIF)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(INVISIBLE_GIF)

    def print_request(self):
        address = urlsplit(self.path)
        print(f"\n[{datetime.now():%H:%M:%S}] received {address.path}")
        for name, value in parse_qsl(address.query):
            print(f"    {name} = {value}")
        # Which page made the browser ask; empty when the page sends no referrer.
        print(f"    (sent by the page: {self.headers.get('Referer', 'not told')})")
        sys.stdout.flush()

    def log_message(self, format, *args):
        pass  # print_request already shows each request


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9911
    server = ThreadingHTTPServer(("127.0.0.1", port), LeakListener)
    print(f"Pretend attacker listening on 127.0.0.1 port {port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
