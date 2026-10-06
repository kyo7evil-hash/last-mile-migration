"""Last Mile Migration Checklist — backend for Substrait.

A tiny JSON document store that the frontend's `claude-shim.js` talks to, so the same
page (lastmile-checklist.html) runs both on claude.ai and on Substrait.

Collections:
  base   — the device list parsed from the migration workbook (meta + p0..pN chunks).
           Written only by admins (ADMIN_EMAILS) via "Upload new workbook".
  edits  — one document per asset tag with checklist changes (status check, remarks, …).

Contract: port 8000, GET /health, API under /api. OceanBase (MySQL wire) via asyncmy with
%s placeholders. All DDL lives in resources/db/migration. Without DATABASE_URL (local dev)
an in-memory store is used instead.
"""
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

import asyncmy
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

COLLECTIONS = {"base", "edits"}
ADMIN_ONLY = {"base"}
ID_RE = re.compile(r"^[A-Za-z0-9_\-.~:@+]{1,150}$")
MAX_DOC_BYTES = 512 * 1024

ADMIN_EMAILS = {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}
# Google SSO (portal → Access tab) must be ON: the platform's auth proxy then sends the
# signed-in user's email as X-Forwarded-Email. Every data route refuses requests without it.
# Set REQUIRE_LOGIN=false only for local development.
REQUIRE_LOGIN = os.getenv("REQUIRE_LOGIN", "true").lower() != "false"

_pool = None
_mem: dict[str, dict[str, dict]] = {c: {} for c in COLLECTIONS}  # local-dev fallback
_mem_rev: dict[str, int] = {c: 0 for c in COLLECTIONS}


def _dsn() -> dict:
    u = urlparse(os.environ["DATABASE_URL"])
    return {
        "host": u.hostname,
        "port": u.port or 2881,
        "user": unquote(u.username or ""),
        "password": unquote(u.password or ""),
        "db": (u.path or "/").lstrip("/"),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool
    if os.getenv("DATABASE_URL"):
        _pool = await asyncmy.create_pool(**_dsn(), autocommit=True)
    yield
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()


app = FastAPI(title="Last Mile Migration Checklist", lifespan=lifespan)


# ---------- identity ----------
def _email(request: Request) -> str | None:
    e = request.headers.get("x-forwarded-email")
    return e.strip().lower() if e else None


def _is_admin(email: str | None) -> bool:
    # No ADMIN_EMAILS configured → every signed-in user may upload (set it in the portal!).
    if REQUIRE_LOGIN and email is None:
        return False
    return not ADMIN_EMAILS or (email is not None and email in ADMIN_EMAILS)


def _require_user(request: Request) -> str | None:
    email = _email(request)
    if REQUIRE_LOGIN and email is None:
        raise HTTPException(401, "Sign in with your Google account to use this app")
    return email


def _check(coll: str, doc_id: str | None = None):
    if coll not in COLLECTIONS:
        raise HTTPException(404, "Unknown collection")
    if doc_id is not None and not ID_RE.match(doc_id):
        raise HTTPException(400, "Invalid document id")


# ---------- models ----------
class Health(BaseModel):
    status: str


class Me(BaseModel):
    email: str | None
    admin: bool
    can_write: bool
    login_required: bool


class Version(BaseModel):
    version: int


class Doc(BaseModel):
    id: str
    data: dict


class DocList(BaseModel):
    version: int
    docs: list[Doc]


class Ok(BaseModel):
    ok: bool


# ---------- storage ----------
async def _rev(coll: str) -> int:
    if _pool is None:
        return _mem_rev[coll]
    async with _pool.acquire() as conn, conn.cursor() as cur:
        await cur.execute("SELECT rev FROM coll_rev WHERE coll = %s", (coll,))
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def _bump(cur, coll: str):
    await cur.execute(
        "INSERT INTO coll_rev (coll, rev) VALUES (%s, 1) ON DUPLICATE KEY UPDATE rev = rev + 1", (coll,)
    )


# ---------- routes ----------
@app.get("/health", response_model=Health)
def health():
    return {"status": "ok"}


@app.get("/api/me", response_model=Me)
def me(request: Request):
    email = _email(request)
    signed_in = email is not None or not REQUIRE_LOGIN
    return {"email": email, "admin": _is_admin(email), "can_write": signed_in, "login_required": REQUIRE_LOGIN}


@app.get("/api/docs/{coll}/version", response_model=Version)
async def version(coll: str, request: Request):
    _require_user(request)
    _check(coll)
    return {"version": await _rev(coll)}


@app.get("/api/docs/{coll}", response_model=DocList)
async def list_docs(coll: str, request: Request):
    _require_user(request)
    _check(coll)
    if _pool is None:
        return {"version": _mem_rev[coll], "docs": [{"id": k, "data": v} for k, v in sorted(_mem[coll].items())]}
    async with _pool.acquire() as conn, conn.cursor() as cur:
        await cur.execute("SELECT rev FROM coll_rev WHERE coll = %s", (coll,))
        row = await cur.fetchone()
        await cur.execute("SELECT doc_id, data FROM docs WHERE coll = %s ORDER BY doc_id", (coll,))
        rows = await cur.fetchall()
    return {"version": int(row[0]) if row else 0, "docs": [{"id": r[0], "data": json.loads(r[1])} for r in rows]}


@app.put("/api/docs/{coll}/{doc_id}", response_model=Ok)
async def put_doc(coll: str, doc_id: str, request: Request):
    _check(coll, doc_id)
    email = _require_user(request)
    if coll in ADMIN_ONLY and not _is_admin(email):
        raise HTTPException(403, "Only admins can upload the workbook")
    raw = await request.body()
    if len(raw) > MAX_DOC_BYTES:
        raise HTTPException(413, "Document too large")
    try:
        data = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "Body must be JSON")
    if not isinstance(data, dict):
        raise HTTPException(400, "Body must be a JSON object")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if coll == "edits" and email:
        # Who/when is stamped server-side from the SSO identity, never trusted from the client.
        data["by"] = email
        data["at"] = now.isoformat(timespec="seconds") + "Z"
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if _pool is None:
        _mem[coll][doc_id] = data
        _mem_rev[coll] += 1
        return {"ok": True}
    async with _pool.acquire() as conn, conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO docs (coll, doc_id, data, updated_at, updated_by) VALUES (%s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE data = VALUES(data), updated_at = VALUES(updated_at), updated_by = VALUES(updated_by)",
            (coll, doc_id, body, now, email),
        )
        await _bump(cur, coll)
    return {"ok": True}


@app.delete("/api/docs/{coll}/{doc_id}", response_model=Ok)
async def delete_doc(coll: str, doc_id: str, request: Request):
    _check(coll, doc_id)
    email = _require_user(request)
    if coll in ADMIN_ONLY and not _is_admin(email):
        raise HTTPException(403, "Only admins can upload the workbook")
    if _pool is None:
        _mem[coll].pop(doc_id, None)
        _mem_rev[coll] += 1
        return {"ok": True}
    async with _pool.acquire() as conn, conn.cursor() as cur:
        await cur.execute("DELETE FROM docs WHERE coll = %s AND doc_id = %s", (coll, doc_id))
        await _bump(cur, coll)
    return {"ok": True}
