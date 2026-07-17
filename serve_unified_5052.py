"""Unified React SPA + API proxy so remote works while elevated :5050 is stuck."""
import os, sys
from pathlib import Path
from flask import Flask, request, Response, send_from_directory
import urllib.request

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "web" / "dashboard-ui" / "dist"
API = "http://127.0.0.1:5050"
app = Flask(__name__, static_folder=None)

@app.route("/api/<path:path>", methods=["GET","POST","PUT","DELETE","OPTIONS","PATCH"])
def api_proxy(path):
    url = f"{API}/api/{path}"
    if request.query_string:
        url += "?" + request.query_string.decode()
    data = request.get_data()
    req = urllib.request.Request(url, data=data or None, method=request.method)
    for h, v in request.headers:
        if h.lower() not in ("host","content-length","transfer-encoding","connection"):
            req.add_header(h, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
            excluded = {"transfer-encoding","connection","content-encoding"}
            headers = [(k,v) for k,v in resp.headers.items() if k.lower() not in excluded]
            return Response(body, status=resp.status, headers=headers)
    except Exception as e:
        return Response(str(e), status=502)

@app.route("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(DIST / "assets", filename)

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def spa(path):
    if path and (DIST / path).is_file():
        return send_from_directory(DIST, path)
    return send_from_directory(DIST, "index.html")

if __name__ == "__main__":
    print("UNIFIED_PROXY_5052", flush=True)
    app.run(host="127.0.0.1", port=5052, threaded=True)
