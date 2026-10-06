# Last Mile Migration Checklist: Technical Document

| | |
|---|---|
| **App** | Last Mile Migration Checklist |
| **Owner** | sanusi.othman@ninjavan.co (IT, Ninja Van Malaysia) |
| **Live URL (dev)** | https://last-mile-migration--dev.ninjavan.apps.substrait.build |
| **Source** | https://github.com/kyo7evil-hash/last-mile-migration (private, branch `main`) |
| **Hosting** | Substrait (app slug `last-mile-migration`, GitHub-connected) |
| **Document date** | 6 Oct 2026 |

For day-to-day use (how to tick steps, filters, upload), see [README.md](README.md). This document covers how the app is built, where data lives, and how to run, change and deploy it.

---

## 1. Purpose and scope

The app tracks the clean-up of Last Mile laptops during the Windows 11 migration. It replaces an Excel sheet where progress was posted as comments.

- **In scope:** 32 laptops from `Last Mile windows 11 migration.xlsx`. Each one has 4 checklist steps, remarks, and replacement-laptop details.
- **Users:** the IT team updates it. Anyone in the Ninja Van Google organisation can sign in.
- **Source of truth:** the Excel file is loaded once by an admin. From then on, the web app is the source of truth.

---

## 2. Architecture

```
 Browser (team member)
   │  https://last-mile-migration--dev.ninjavan.apps.substrait.build
   ▼
 Substrait ingress + Google SSO proxy ──► adds X-Forwarded-Email header
   │
   ├── /api/*, /health ──► Backend container (FastAPI, port 8000) ──► OceanBase DB (MySQL wire)
   │
   └── everything else ──► Frontend container (nginx, port 80)
                             serves index.html = lastmile-checklist.html + claude-shim.js
```

| Layer | Technology | File(s) |
|---|---|---|
| **Page (UI)** | One HTML file with plain JavaScript and CSS. SheetJS 0.18.5 (from cdnjs) reads and writes Excel. Fonts come from Google Fonts: Archivo, IBM Plex Sans and IBM Plex Mono. | `lastmile-checklist.html` |
| **Data adapter** | `window.claude.use()` stand-in. It maps `db`, `user` and `downloads` calls onto `/api`, and polls every 5 seconds for live updates. | `frontend/claude-shim.js` |
| **Backend** | Python 3.12, FastAPI and uvicorn. A small JSON document store, using the `asyncmy` driver. | `backend/main.py`, `backend/requirements.txt` |
| **Database** | OceanBase, provisioned by Substrait, which injects `DATABASE_URL`. | `backend/resources/db/migration/V1__docs.sql` |
| **Containers** | `python:3.12-slim` for the backend, `nginx:1.27-alpine` for the frontend | `cicd/Dockerfile.backend`, `cicd/Dockerfile.frontend`, `cicd/nginx.conf` |
| **Platform config** | App description and database declaration | `substrait.yaml` |
| **API description** | OpenAPI 3 spec, published to the Substrait API Library | `openapi.json` |

**Design note:** the architecture is copied from the *Windows 11 Migration Dashboard* (`win11-migration-tracker`). The backend and shim are identical apart from naming, so fixes to one can be ported to the other.

**Why this design:** the page is written against the claude.ai Artifact runtime API (`window.claude.use`). The shim lets the same page run on Substrait with no code changes, and the backend stays a generic document store, so all app logic lives in one HTML file.

---

## 3. Data model

### 3.1 Database tables (OceanBase)

Defined in `V1__docs.sql` and applied by Flyway on deploy. The application never creates tables itself.

| Table | Columns | Purpose |
|---|---|---|
| `docs` | `coll` VARCHAR(64), `doc_id` VARCHAR(200), `data` LONGTEXT (JSON), `updated_at` DATETIME(6), `updated_by` VARCHAR(255). Primary key is (`coll`, `doc_id`). | One row per document |
| `coll_rev` | `coll` VARCHAR(64) primary key, `rev` BIGINT | Revision counter per collection. It goes up on every write, which lets clients poll cheaply. |

### 3.2 Collections

| Collection | Document ID | Content | Who can write |
|---|---|---|---|
| `base` | `meta` | `{ chunks, count, file, by, at }` describes the last workbook upload | Admins only |
| `base` | `p0` … `pN` | `{ rows: [Laptop, …] }`, holding up to 150 laptops per chunk | Admins only |
| `edits` | asset tag, e.g. `NV00029544` | Changes made on the web for that laptop. For laptops added on the web, it also holds `added: { region, hub, assigned, serial, brand, model, position, by, at }`. | Any signed-in user |

**Laptop record** (in `base`, parsed from the workbook):

```json
{
  "tag": "NV00029544", "region": "East Coast 1", "hub": "No hub",
  "assigned": "syafiq.dawot@…", "serial": "8XF5GD3", "snipeStatus": "Deployed (deployed)",
  "brand": "DELL", "model": "P090F", "lastSync": "…", "dept": "Last Mile",
  "position": "Region Head, Last Mile", "latestUser": "…", "remarks": "",
  "newSerial": "", "newTag": "", "ticket": "", "tn": "",
  "steps": { "ret": "done", "repl": "pending", "win11": "done", "snipe": "pending" }
}
```

**Edit record** (in `edits`): holds only the fields changed on the web. The server always overwrites `by` and `at` using the signed-in user's identity.

```json
{ "steps": { "snipe": "done" }, "remarks": "Collected 3 Oct", "by": "aiman.aqil@…", "at": "2026-10-06T07:12:03Z" }
```

### 3.3 Checklist steps

| Key | Label | Possible values |
|---|---|---|
| `ret` | Return to IT | `pending`, `done` or `na` |
| `repl` | Replacement to hub | same |
| `win11` | Win 11 updated | same |
| `snipe` | Snipe-IT updated | same |

**Rules calculated in the page:**
- **Complete:** every step is `done` or `na`.
- **In progress:** not complete, and at least one step is `done`.
- **Not started:** no step is `done`.
- **Card progress:** "X of Y done", where Y is the number of steps that are not `na`.

### 3.4 How base and edits combine

The page shows `effective = base` with `edits[tag]` laid on top.

- Steps are combined key by key.
- The edited text fields (`latestUser`, `remarks`, `newSerial`, `newTag`, `ticket`, `tn`) replace the base values when they are present.
- Re-uploading a workbook replaces `base`. **Edits made on the web always win over workbook values.**
- **Laptops added on the web** (`edits/<tag>` with an `added` object) are appended to the list, with all steps Pending. If a later workbook contains the same tag, the workbook row is used instead, and the web edits still apply on top. Removing an added laptop deletes its `edits/<tag>` document.

---

## 4. Workbook import

The import is done in the browser by `parseWorkbook()` in `lastmile-checklist.html`. Only admins can see the **Upload workbook** button.

| Source | How the sheet is found | Fields used |
|---|---|---|
| Laptop sheet (`Sheet1`) | The first sheet with the headers `Tagging` and `Win 11 update` | Tagging, Region, Hub, User assign from snipe it, Serialnumber, Snipe it status, Laptop brand, Laptop model, Last sync user, Department, Position, Latest User, Remarks, Return to IT, Replacement to hub, Win 11 update |
| Replacement sheet (`LM`) | The first other sheet with a `TN` (or `Done Return`) header. Rows are matched to laptops by `Tagging`. | Serial No. → `newSerial`, Tagging No. → `newTag`, Ticket → `ticket`, TN → `tn`. Region, Hub and Station are used as fallbacks. |

**Mapping rules:**
- **Header names:** spaces are trimmed and case is ignored, so `Ticket ` matches `ticket`.
- **Tick values:** `TRUE`, `1`, `yes`, `y` or `done` become `done`. Anything else becomes `pending`. (Excel checkboxes come through as TRUE/FALSE.)
- **Remarks containing "no need replacement":** the Replacement step is set to `na`.
- **Snipe-IT updated:** starts as `pending` for every laptop, because it isn't in the workbook.
- **Brand:** the "MY -" prefix is removed, so `MY - DELL` becomes `DELL`.
- **Missing region or hub:** shown as "No region" / "No hub".
- **Skipped rows:** rows with no tag, duplicate tags, and tags with characters not allowed in a document ID.

**Check against the 6 Oct 2026 workbook:** 32 laptops loaded. Return to IT = 18, Win 11 updated = 7, Replacement = 17 done and 4 N/A, and 13 laptops have replacement details. All figures match the sheet.

---

## 5. API

The full spec is in `openapi.json`. All `/api/docs` routes require a signed-in user.

| Method and path | Purpose |
|---|---|
| `GET /health` | Readiness check. Returns `{"status":"ok"}`. Needs no sign-in. |
| `GET /api/me` | Current user: `{ email, admin, can_write, login_required }` |
| `GET /api/docs/{coll}/version` | Revision number of the collection, which the client polls every 5 seconds |
| `GET /api/docs/{coll}` | All documents in the collection, plus its version |
| `PUT /api/docs/{coll}/{doc_id}` | Create or replace a document (JSON object, at most 512 KB) |
| `DELETE /api/docs/{coll}/{doc_id}` | Delete a document |

**Validation:**
- `coll` must be `base` or `edits`.
- `doc_id` must match `^[A-Za-z0-9_\-.~:@+]{1,150}$`.

**Errors:**

| Code | Meaning |
|---|---|
| 401 | Not signed in. The page shows a "Sign in required" screen. |
| 403 | Not an admin, when writing to `base` |
| 404 | Unknown collection |
| 413 | Document too large |

---

## 6. Security and access

| Control | How it works |
|---|---|
| **Sign-in** | Substrait's Google SSO proxy. The dev environment is always behind organisation sign-in. The proxy adds `X-Forwarded-Email`, which browsers can't fake. |
| **Login enforcement** | `REQUIRE_LOGIN=true`. Any `/api/docs` request without an email gets 401. |
| **Admin rights** | `ADMIN_EMAILS` (comma-separated) decides who can write `base`. **If it is left empty, every signed-in user counts as an admin**, so always keep it set. |
| **Audit stamp** | The server writes `by` and `at` on each edit from the SSO identity. The page shows "Updated by …" on each card. |
| **Personal data** | Staff emails exist only in the database and the workbook. `.gitignore` excludes `*.xlsx`, `*.xls` and `*.csv`, so the workbook is never pushed to GitHub. |
| **Platform scans** | Each deploy runs Gitleaks, Trivy, Dependency-Check and Semgrep. Latest results: Gitleaks and Dependency-Check found nothing. Semgrep reported findings, which should be reviewed in the Substrait portal (Deploys → run → Semgrep). |

**Environment variables** (Substrait portal → app → Settings; defaults come from `backend/.env.example`):

| Name | Current value | Meaning |
|---|---|---|
| `ADMIN_EMAILS` | `sanusi.othman@ninjavan.co` | Who can upload or replace the workbook |
| `REQUIRE_LOGIN` | `true` | Set to `false` only for local development |
| `DATABASE_URL` | injected by the platform | OceanBase connection |

---

## 7. Frontend behaviour

| Area | Details |
|---|---|
| **Tabs** | **Summary:** headline completion, progress per step, progress per region. Step and region rows are clickable and open the filtered checklist. **Checklist:** one card per laptop. |
| **Steps** | Clicking a step cycles `pending → done → na → pending`. The change shows immediately (optimistic update), then saves to `edits/<tag>`. If the save fails, it rolls back and shows a message. |
| **Detail panel** | A `<dialog>` with the steps, read-only laptop facts, and editable Latest user, Remarks and replacement fields. **Save changes** writes only the fields that changed. |
| **Filters** | Search (tag, serial, users, hub, region, brand, model, remarks, ticket, new serial or tag, TN), region, hub, a "waiting on step" filter (set from the Summary tab), and Not complete / Complete / All |
| **Sort** | Region then hub (default), hub, least done first, most done first, tag, or recently changed |
| **Add / remove laptops** | **+ Add laptop** (any signed-in user) opens a form. The tag is required, upper-cased, must be unique and must be a valid document ID. Region, hub and brand suggest existing values. Saved via `saveEdit(tag, { added, latestUser?, remarks? })`. **Remove laptop** appears only for added laptops and needs two clicks. |
| **Export** | **Download Excel** writes the current filtered view to `last-mile-checklist-YYYY-MM-DD.xlsx` |
| **Theme** | Light and dark colour sets defined as CSS variables. It follows the system setting by default. The **Day / Night mode** button overrides it. |
| **Saved in each browser (localStorage)** | `lm-tab` (last tab), `lm-sort` (sort order), `lm-theme` (light or dark). Nothing shared is kept in browser storage. |
| **Live updates** | The shim polls `/api/docs/{coll}/version` every 5 seconds, and immediately when the tab becomes visible again. It reloads a collection only when its version has changed. |
| **Layout** | Responsive. Cards fill a grid at least 290 px wide and become one column on phones, with no sideways scrolling. |

---

## 8. Running locally

You need Python 3.12 or newer. No database is needed, because with no `DATABASE_URL` the backend uses an in-memory store that is cleared on restart.

```bash
python3 -m venv /tmp/lm-venv
```
```bash
/tmp/lm-venv/bin/pip install fastapi "uvicorn[standard]" asyncmy
```
```bash
/tmp/lm-venv/bin/uvicorn --app-dir dev devserver:app --port 8765
```

Then open http://localhost:8765.

`dev/devserver.py` does the following:
- serves the page wrapped the same way as `cicd/Dockerfile.frontend`;
- serves the shim at `/claude-shim.js`;
- serves the workbook at `/test.xlsx`, for local testing only;
- turns login off and treats every user as an admin.

To load test data in the browser console:
`await uploadFile(new File([await fetch('/test.xlsx').then(r=>r.arrayBuffer())], 'test.xlsx'))`

Note: macOS may block running a virtual environment from inside the Desktop folder. If so, create it under `/tmp`, as shown above.

---

## 9. Deploying changes

The app is **GitHub-connected**, so Substrait builds the pushed `main` branch, not your local files.

1. Edit the files, then test locally (section 8).
2. Commit and push to `main`.
3. Deploy, either with `/substrait:deploy` in Claude Code or with:
   ```bash
   bash ~/.claude/plugins/cache/substrait/substrait/<version>/scripts/substrait-deploy.sh --watch
   ```
   The deploy goes through these stages: clone → contract check → security scans → build images → Flyway migration → rollout → preview live.
4. Check the live URL. If something fails at runtime, use `/substrait:logs`.

**Rules:**
- The deploy refuses to run if there are uncommitted or unpushed changes.
- The deploy script may write a `scaffold_version` stamp into `substrait.yaml`. That stamp must be committed and pushed too.
- Never create a `k8s/` folder. The platform owns that.
- Any database schema change goes in a **new** file, e.g. `V2__….sql`. Never edit `V1__docs.sql`.
- If backend routes change, regenerate `openapi.json`.
- The app only has a **dev** environment. A public production version needs a promotion, which triggers Substrait's security review (Layers 1–4), and starts with an empty database.

**Substrait GitHub App access:** the Substrait GitHub App needs access to this repository. On 6 Oct 2026 its access list contained only `last-mile-migration`. To fix it, go to https://github.com/settings/installations → Substrait → Configure, and check that other apps' repos (such as `win11-migration-tracker`) are still included.

---

## 10. Common changes

| Change | Where |
|---|---|
| Add, rename or reorder a checklist step | The `STEPS` array in `lastmile-checklist.html`. Also set its starting value in `parseWorkbook()` under `steps:`. Existing edits keep working because they are stored by step key. |
| Add an editable text field | Add it to `EDIT_FIELDS`, add an input in `openDetail()`, and add a column in the export function |
| Add a column from the workbook | `parseWorkbook()`, which reads headers in lower case. Then show it in `cardHTML()` and/or `openDetail()`. |
| Change who can upload | `ADMIN_EMAILS` in the Substrait portal. No redeploy is needed beyond the portal's own restart. |
| Change colours or fonts | The CSS variables at the top of the `<style>` block. Update the light set and both dark-mode blocks. |
| Change the live-update interval | `POLL_MS` in `frontend/claude-shim.js` |

---

## 11. Known limitations

| Limitation | Effect | Possible fix |
|---|---|---|
| **Last write wins on the same laptop** | Each save rewrites the whole `edits/<tag>` document from the browser's copy. If two people change the *same* laptop within the 5-second poll window, the later save can undo the earlier one. | Add a server-side merge (PATCH) or version check on `edits` |
| **No full change history** | Only the latest `by` / `at` per laptop is kept | Add an `audit` table, written by the backend on each PUT |
| **Polling instead of push** | Changes take up to 5 seconds to appear for others | Fine at this scale (32 laptops, a small team) |
| **Workbook data quality** | 6 laptops have no region, and some hubs are blank or labelled differently (e.g. `OUG` vs `Zone H`). The original data is kept as it is. | Clean the source sheet and re-upload. Web edits are kept. |
| **Removing laptops** | Re-uploading with fewer rows hides missing laptops, but their `edits` documents stay in the database | Usually harmless. They can be deleted through the API. |
| **Edits limit** | The page loads up to 1,000 edit documents | Far above the current 32 |
| **Dev environment only** | No production URL. Everyone must sign in with an organisation account. | Promote to production if public access is ever needed |

---

## 12. Change log

| Date | Change |
|---|---|
| 2 Oct 2026 | Built the page and backend from the Win11 tracker pattern. Workbook import tested locally. |
| 6 Oct 2026 | Created GitHub repo and Substrait app, deployed to dev, workbook uploaded (32 laptops). |
| 6 Oct 2026 | Added the Day / Night mode switch. |
| 6 Oct 2026 | Checklist tab redesigned: a card per laptop with tick boxes, status badges, progress per card, sort options, and a tidier filter bar. |
| 6 Oct 2026 | Added this technical document. |
| 6 Oct 2026 | Added **+ Add laptop** (new cards) and **Remove laptop** for web-added cards. |
| 6 Oct 2026 | Removed the "Done return" step; the checklist now has 4 steps. Saved Done return values remain in the database but are ignored. |
