// Stand-in for the claude.ai artifact runtime (window.claude.use) on Substrait.
// lastmile-checklist.html only uses a small slice of it — db (collection/doc, onSnapshot, set,
// delete), user (id, can, canEdit, profiles) and downloads (save) — so this maps those onto
// the backend's /api/docs store. Live updates come from polling a per-collection revision.
(function () {
  "use strict";
  const POLL_MS = 5000;

  async function api(path, opts = {}) {
    const res = await fetch("/api" + path, { headers: { "Content-Type": "application/json" }, credentials: "same-origin", ...opts });
    if (!res.ok) {
      const err = new Error((await res.text().catch(() => "")) || res.statusText);
      if (res.status === 401) showSignIn();
      err.code = res.status === 403 || res.status === 400 ? "invalid_argument" : res.status === 413 ? "quota_exceeded" : "unavailable";
      throw err;
    }
    return res.json();
  }

  // ---------- sign-in gate ----------
  function showSignIn() {
    if (document.getElementById("signin-gate")) return;
    const run = () => {
      const g = document.createElement("div");
      g.id = "signin-gate";
      g.setAttribute("role", "alertdialog");
      g.style.cssText = "position:fixed;inset:0;z-index:100;display:grid;place-items:center;background:var(--page,#f9f9f7);font:15px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif;color:var(--ink,#0b0b0b);padding:16px";
      g.innerHTML = '<div style="max-width:420px;text-align:center"><h1 style="font-size:20px;margin:0 0 8px">Sign in required</h1>' +
        '<p style="margin:0 0 16px;color:var(--ink-2,#52514e)">This tracker holds staff and device data. Sign in with your company Google account to view and edit it.</p>' +
        '<a id="signin-btn" style="display:inline-block;font:inherit;padding:9px 18px;border-radius:8px;background:#2a78d6;color:#fff;text-decoration:none">Sign in with Google</a></div>';
      document.body.appendChild(g);
      // The platform's SSO proxy serves Google sign-in at /oauth2/start and returns here after.
      g.querySelector("#signin-btn").href = "/oauth2/start?rd=" + encodeURIComponent(location.pathname + location.search + location.hash);
    };
    document.body ? run() : document.addEventListener("DOMContentLoaded", run);
  }

  // ---------- db ----------
  const watchers = new Map(); // collection -> { version, cbs:Set, timer, last }
  const snapshot = docs => ({
    docs: docs.map(d => ({ id: d.id, exists: true, data: () => d.data, metadata: { fromCache: false, hasPendingWrites: false } })),
    size: docs.length,
    empty: docs.length === 0,
    metadata: { fromCache: false, hasPendingWrites: false },
    docChanges: () => [],
  });
  async function poll(coll, force) {
    const w = watchers.get(coll);
    if (!w) return;
    try {
      if (!force && w.version !== null) {
        const { version } = await api(`/docs/${coll}/version`);
        if (version === w.version) return;
      }
      const res = await api(`/docs/${coll}`);
      w.version = res.version;
      w.last = snapshot(res.docs);
      w.cbs.forEach(cb => { try { cb(w.last); } catch (e) { console.error(e); } });
    } catch (e) { /* transient: next poll retries */ }
  }
  function docRef(coll, id) {
    const path = `/docs/${coll}/${encodeURIComponent(id)}`;
    return {
      id, path: `${coll}/${id}`,
      set: data => api(path, { method: "PUT", body: JSON.stringify(data) }).then(() => { poll(coll, true); }),
      delete: () => api(path, { method: "DELETE" }).then(() => { poll(coll, true); }),
    };
  }
  function collection(coll) {
    const q = {
      path: coll,
      limit() { return q; },
      orderBy() { return q; },
      doc: id => docRef(coll, id),
      onSnapshot(cb) {
        let w = watchers.get(coll);
        if (!w) {
          w = { version: null, cbs: new Set(), timer: null, last: null };
          watchers.set(coll, w);
          w.timer = setInterval(() => poll(coll), POLL_MS);
          poll(coll, true);
        } else if (w.last) setTimeout(() => cb(w.last), 0);
        w.cbs.add(cb);
        return () => w.cbs.delete(cb);
      },
    };
    return q;
  }
  const db = Object.freeze({
    collection,
    doc: path => { const i = path.lastIndexOf("/"); return docRef(path.slice(0, i), path.slice(i + 1)); },
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) watchers.forEach((_, c) => poll(c)); });

  // ---------- user ----------
  let mePromise = null;
  const me = () => (mePromise ||= api("/me").then(m => { if (m.login_required && !m.email) showSignIn(); return m; })
    .catch(() => ({ email: null, admin: false, can_write: false, login_required: true })));
  const user = Object.freeze({
    id: async () => (await me()).email,
    can: async name => (name === "data.write" ? (await me()).can_write : false),
    canEdit: async () => (await me()).admin,
    isOwner: async () => (await me()).admin,
    me: async () => { const m = await me(); return { id: m.email, name: m.email || "", email: m.email, isOwner: m.admin, canEdit: m.admin }; },
    profiles: async ids => {
      const m = await me();
      const out = {};
      for (const id of [].concat(ids)) {
        const email = typeof id === "string" && id.includes("@") ? id : null;
        out[id] = { id, name: email || "", email, isMe: !!m.email && id === m.email, guest: false };
      }
      return out;
    },
  });

  // ---------- downloads ----------
  const downloads = Object.freeze({
    save: async ({ filename, data }) => {
      const blob = data instanceof Blob ? data : new Blob([data], { type: filename.endsWith(".csv") ? "text/csv" : "application/octet-stream" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    },
  });

  const caps = { db, user, downloads };
  // No data capability until the viewer is signed in: the page then shows no data at all.
  window.claude = Object.freeze({
    use: name => name === "db" ? me().then(m => (m.email || !m.login_required ? db : null)) : Promise.resolve(caps[name] || null),
  });
})();
