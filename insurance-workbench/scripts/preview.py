"""Serve bundled UI on localhost; Python standard library only."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import webbrowser

root = Path(__file__).resolve().parents[1] / "apps" / "web" / "dist"
server = ThreadingHTTPServer(("127.0.0.1", 5173), partial(SimpleHTTPRequestHandler, directory=str(root)))
print("Preview: http://127.0.0.1:5173 (Ctrl+C to stop)", flush=True)
webbrowser.open("http://127.0.0.1:5173")
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
