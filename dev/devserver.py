"""Local test server: serves the page (wrapped like cicd/Dockerfile.frontend), the shim and the API
from one port, with login off and an in-memory store. Not deployed.
Run:  .venv/bin/uvicorn --app-dir dev devserver:app --port 8765"""
import os, sys
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/"
sys.path.insert(0, PROJ + "backend/")
os.environ["REQUIRE_LOGIN"] = "false"
os.environ["ADMIN_EMAILS"] = ""
from main import app  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse  # noqa: E402

@app.get("/claude-shim.js")
def shim():
    return FileResponse(PROJ + "frontend/claude-shim.js", media_type="text/javascript")

@app.get("/test.xlsx")
def xlsx():
    return FileResponse(PROJ + "Last Mile windows 11 migration.xlsx")

@app.get("/")
def page():
    body = open(PROJ + "lastmile-checklist.html").read()
    return HTMLResponse('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><script src="/claude-shim.js"></script></head><body>' + body + "</body></html>")
