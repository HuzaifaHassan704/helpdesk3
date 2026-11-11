'use strict';
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const ST = ['open', 'in_progress', 'resolved', 'closed'], PR = ['low', 'medium', 'high', 'urgent'], RL = ['employee', 'agent', 'admin'];
const L = s => String(s).replace('_', ' ');
const dt = s => s ? new Date(/(Z|[+-]\d\d:?\d\d)$/i.test(s) ? s : s + 'Z').toLocaleString() : '—';
const opts = (a, cur, all) => (all ? `<option value="">${all}</option>` : '') + a.map(v => `<option value="${v}"${v === cur ? ' selected' : ''}>${L(v)}</option>`).join('');
const badge = (k, v) => `<span class="b ${k}-${v}">${L(v)}</span>`;
const freshQuery = () => ({ status: '', priority: '', search: '', page: 1 });
const S = { token: sessionStorage.getItem('token'), me: null, view: 'tickets', q: freshQuery() };
S.pub = { company_name: 'Helpdesk', registration_open: true };
async function loadPublic() { try { S.pub = await api('/system/public'); } catch { /* keep defaults */ } }
const applyTheme = t => { if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme; };
try { applyTheme(localStorage.getItem('theme')); } catch { /* storage unavailable */ }
const staff = () => S.me.role !== 'employee', admin = () => S.me.role === 'admin';

function toast(m, err) {
  const t = $('#toast'); t.textContent = m; t.className = 'show' + (err ? ' err' : '');
  clearTimeout(toast.t); toast.t = setTimeout(() => t.className = '', 3500);
}

async function api(path, { method = 'GET', json, form } = {}) {
  const h = {}; let body;
  if (S.token) h.Authorization = 'Bearer ' + S.token;
  if (json) { h['Content-Type'] = 'application/json'; body = JSON.stringify(json); }
  else if (form) body = new URLSearchParams(form);
  const r = await fetch(path, { method, headers: h, body });
  if (r.status === 401 && S.token && !path.startsWith('/auth')) { logout(); throw new Error('Session expired, please sign in again'); }
  if (r.status === 204) return null;
  const d = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = d.detail;
    throw new Error(typeof e === 'string' ? e : Array.isArray(e) ? e.map(x => x.loc.slice(1).join('.') + ': ' + x.msg).join('; ') : 'Request failed (' + r.status + ')');
  }
  return d;
}

function logout() { S.token = null; S.me = null; S.q = freshQuery(); sessionStorage.removeItem('token'); closeModal(); authView(); }
async function boot() {
  await loadPublic();
  if (!S.token) return authView();
  try { S.me = await api('/users/me'); S.view = 'tickets'; S.q = freshQuery(); shell(); } catch { logout(); }
}

function authView(mode = 'login') {
  const login = mode === 'login';
  $('#app').innerHTML = `<div class="auth"><h1>🎫 ${esc(S.pub.company_name)}</h1>
  <div class="tabs"><button data-m="login" class="${login ? 'on' : ''}">Sign in</button>${S.pub.registration_open ? `<button data-m="register" class="${login ? '' : 'on'}">Register</button>` : ''}</div>
  <form id="af">${login ? '' : '<label>Full name<input name="full_name" required maxlength="120"></label>'}
  <label>Email<input name="email" type="email" required autocomplete="username"></label>
  <label>Password<input name="password" type="password" required minlength="8" autocomplete="${login ? 'current-password' : 'new-password'}"></label>
  <button class="primary">${login ? 'Sign in' : 'Create account'}</button></form>
  <p class="hint">New accounts are Employees. Admins create Agents under Users.</p></div>`;
  $('.tabs').onclick = e => { if (e.target.dataset.m) authView(e.target.dataset.m); };
  $('#af').onsubmit = async e => {
    e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    try {
      if (!login) await api('/auth/register', { method: 'POST', json: f });
      const t = await api('/auth/login', { method: 'POST', form: { username: f.email, password: f.password } });
      S.token = t.access_token; sessionStorage.setItem('token', S.token); await boot();
    } catch (x) { toast(x.message, 1); }
  };
}

function shell() {
  const nav = [['tickets', 'Tickets'], ...(staff() ? [['dashboard', 'Dashboard']] : []), ...(admin() ? [['users', 'Users'], ['settings', 'Settings']] : [])];
  $('#app').innerHTML = `<header><b>🎫 ${esc(S.pub.company_name)}</b><nav>${nav.map(([k, n]) => `<button data-v="${k}" class="${S.view === k ? 'on' : ''}">${n}</button>`).join('')}</nav>
  <span class="who">${esc(S.me.full_name)}<i>${S.me.role}</i></span><button id="th" title="Switch theme">◐</button><button id="pw">Password</button><button id="lo">Log out</button></header><main id="main"></main>`;
  $('nav').onclick = e => { if (e.target.dataset.v) { S.view = e.target.dataset.v; shell(); } };
  $('#lo').onclick = logout;
  $('#pw').onclick = openPassword;
  $('#th').onclick = () => {
    const n = { null: 'light', light: 'dark', dark: null }[localStorage.getItem('theme')];
    if (n) localStorage.setItem('theme', n); else localStorage.removeItem('theme');
    applyTheme(n); toast('Theme: ' + (n || 'auto'));
  };
  ({ tickets: viewTickets, dashboard: viewDashboard, users: viewUsers, settings: viewSettings })[S.view]();
}

/* ---------- tickets ---------- */
function viewTickets() {
  const q = S.q;
  $('#main').innerHTML = `<div class="bar"><input id="qs" type="search" placeholder="Search title or description…" value="${esc(q.search)}">
  <select id="qst">${opts(ST, q.status, 'All statuses')}</select><select id="qpr">${opts(PR, q.priority, 'All priorities')}</select>
  ${staff() ? '<button id="ex" title="Download the filtered list">⬇ CSV</button>' : ''}${S.me.role !== 'agent' ? '<button class="primary" id="nb">＋ New ticket</button>' : ''}</div><div id="list"></div>`;
  const upd = () => { q.search = $('#qs').value.trim(); q.status = $('#qst').value; q.priority = $('#qpr').value; q.page = 1; loadTickets(); };
  $('#qs').onchange = upd; $('#qst').onchange = upd; $('#qpr').onchange = upd;
  if ($('#nb')) $('#nb').onclick = openNew;
  if ($('#ex')) $('#ex').onclick = exportCsv;
  $('#list').onclick = e => {
    const tr = e.target.closest('tr[data-id]'), b = e.target.closest('button[data-p]');
    if (tr) openTicket(tr.dataset.id);
    if (b) { q.page += +b.dataset.p; loadTickets(); }
  };
  loadTickets();
}

async function loadTickets() {
  const q = S.q, p = new URLSearchParams({ page: q.page, limit: 10 });
  ['status', 'priority', 'search'].forEach(k => q[k] && p.set(k, q[k]));
  try {
    const d = await api('/tickets/?' + p);
    $('#list').innerHTML = (d.items.length ? `<div class="tw"><table><thead><tr><th>#</th><th>Title</th><th>Status</th><th>Priority</th><th>Assignee</th><th>Created</th></tr></thead><tbody>${d.items.map(t =>
      `<tr data-id="${t.id}"><td>${t.id}</td><td>${esc(t.title)}</td><td>${badge('s', t.status)}${t.is_overdue ? ' <span class="b p-urgent">overdue</span>' : ''}</td><td>${badge('p', t.priority)}</td><td>${t.assignee_id ? (t.assignee_id === S.me.id ? 'You' : '#' + t.assignee_id) : '—'}</td><td>${dt(t.created_at)}</td></tr>`).join('')}</tbody></table></div>` : '<p class="empty">No tickets found.</p>') +
      `<div class="pg"><button data-p="-1" ${d.has_prev ? '' : 'disabled'}>← Prev</button><span>Page ${d.page} of ${Math.max(d.pages, 1)} · ${d.total} ticket${d.total === 1 ? '' : 's'}</span><button data-p="1" ${d.has_next ? '' : 'disabled'}>Next →</button></div>`;
  } catch (x) { toast(x.message, 1); }
}

function modal(html) {
  const m = $('#modal'); m.innerHTML = `<div class="ov"><div class="dlg">${html}</div></div>`;
  m.onclick = e => { if (e.target.classList.contains('ov') || e.target.dataset.a === 'x') closeModal(); };
  return $('.dlg', m);
}
function closeModal() { $('#modal').innerHTML = ''; }
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

function openNew() {
  modal(`<h2>New ticket</h2><form id="nf"><label>Title<input name="title" required minlength="3" maxlength="200"></label>
  <label>Description<textarea name="description" rows="5" required></textarea></label>
  <label>Priority<select name="priority">${opts(PR, 'medium')}</select></label>
  <div class="acts"><button type="button" data-a="x">Cancel</button><button class="primary">Create</button></div></form>`);
  $('#nf').onsubmit = async e => {
    e.preventDefault();
    try { await api('/tickets/', { method: 'POST', json: Object.fromEntries(new FormData(e.target)) }); closeModal(); toast('Ticket created'); S.q.page = 1; loadTickets(); }
    catch (x) { toast(x.message, 1); }
  };
}

async function openTicket(id) {
  let t, cs, hist;
  try { [t, cs, hist] = await Promise.all([api('/tickets/' + id), api(`/tickets/${id}/comments`), api(`/tickets/${id}/history`)]); } catch (x) { return toast(x.message, 1); }
  const lock = !staff() && t.status === 'closed', txt = admin() || (!staff() && !lock);
  const d = modal(`<div class="hd"><h2>#${t.id} ${badge('s', t.status)}</h2><button data-a="x">✕</button></div>
  <label>Title<input id="ft" value="${esc(t.title)}" ${txt ? '' : 'disabled'}></label>
  <label>Description<textarea id="fdesc" rows="4" ${txt ? '' : 'disabled'}>${esc(t.description)}</textarea></label>
  <div class="two"><label>Status<select id="fs" ${staff() && t.allowed_statuses.length ? '' : 'disabled'}>${opts([t.status, ...t.allowed_statuses], t.status)}</select></label>
  <label>Priority<select id="fp" ${lock ? 'disabled' : ''}>${opts(PR, t.priority)}</select></label></div>
  <p class="meta">Created ${dt(t.created_at)} by #${t.creator_id} · Assignee: ${t.assignee_id ? '#' + t.assignee_id : 'none'}${t.resolved_at ? ' · Resolved ' + dt(t.resolved_at) : ''}</p>
  <p class="meta">Due: ${dt(t.due_at)}${t.is_overdue ? ' <span class="b p-urgent">overdue</span>' : ''}</p>
  <div class="acts">${admin() ? '<button class="danger" data-a="del">Delete</button>' : ''}${!staff() && t.allowed_statuses.includes('closed') ? '<button data-a="close">Close ticket</button>' : ''}${!staff() && t.allowed_statuses.includes('open') ? '<button data-a="reopen">Reopen</button>' : ''}<button class="primary" data-a="save" ${lock ? 'disabled' : ''}>Save changes</button></div>
  ${staff() ? '<div class="bar"><button data-a="me">Assign to me</button><input id="fa" type="number" min="1" placeholder="Agent user ID"><button data-a="as">Assign</button></div>' : ''}
  <h3>Comments</h3>${cs.length ? cs.map(c => `<div class="c${c.is_internal ? ' int' : ''}"><small>#${c.author_id}${c.author_id === S.me.id ? ' (you)' : ''} · ${dt(c.created_at)}${c.is_internal ? ' · internal note' : ''}</small><p>${esc(c.body)}</p></div>`).join('') : '<p class="empty">No comments yet.</p>'}
  <h3>History</h3><ul class="hist">${hist.map(h => `<li><small>${dt(h.created_at)} · ${h.actor_id ? '#' + h.actor_id : 'system'}</small> ${esc(L(h.event))}${h.detail ? ': ' + esc(h.detail) : ''}</li>`).join('')}</ul>
  ${lock ? '<p class="empty">This ticket is closed, so comments are turned off.</p>' : `<form id="cf"><textarea name="body" rows="2" placeholder="Write a comment…" required></textarea><div class="acts">${staff() ? '<label class="chk"><input type="checkbox" name="is_internal"> Internal note</label>' : ''}<button class="primary">Post comment</button></div></form>`}`);
  const run = async (fn, msg) => { try { await fn(); toast(msg); openTicket(id); if ($('#list')) loadTickets(); } catch (x) { toast(x.message, 1); } };
  const patch = j => api('/tickets/' + id, { method: 'PATCH', json: j });
  const assign = j => api(`/tickets/${id}/assign`, { method: 'POST', json: j });
  d.onclick = e => {
    const a = e.target.dataset.a; if (!a || a === 'x') return;
    if (a === 'save') {
      const j = {};
      if (txt) { if ($('#ft').value !== t.title) j.title = $('#ft').value; if ($('#fdesc').value !== t.description) j.description = $('#fdesc').value; }
      if (staff() && $('#fs').value !== t.status) j.status = $('#fs').value;
      if (!lock && $('#fp').value !== t.priority) j.priority = $('#fp').value;
      return Object.keys(j).length ? run(() => patch(j), 'Saved') : toast('Nothing to save');
    }
    if (a === 'close') return run(() => patch({ status: 'closed' }), 'Ticket closed');
    if (a === 'reopen') return run(() => patch({ status: 'open' }), 'Ticket reopened');
    if (a === 'me') return run(() => assign({}), 'Assigned to you');
    if (a === 'as') { const v = +$('#fa').value; return v ? run(() => assign({ assignee_id: v }), 'Assigned') : toast('Enter a user ID', 1); }
    if (a === 'del' && confirm('Delete this ticket permanently?'))
      api('/tickets/' + id, { method: 'DELETE' }).then(() => { closeModal(); toast('Ticket deleted'); loadTickets(); }).catch(x => toast(x.message, 1));
  };
  if ($('#cf')) $('#cf').onsubmit = e => {
    e.preventDefault(); const f = new FormData(e.target);
    run(() => api(`/tickets/${id}/comments`, { method: 'POST', json: { body: f.get('body'), is_internal: !!f.get('is_internal') } }), 'Comment added');
  };
}

/* ---------- account & export ---------- */
function openPassword() {
  modal(`<h2>Change password</h2><form id="pf"><label>Current password<input name="current_password" type="password" required autocomplete="current-password"></label>
  <label>New password (8+ characters)<input name="new_password" type="password" required minlength="8" autocomplete="new-password"></label>
  <div class="acts"><button type="button" data-a="x">Cancel</button><button class="primary">Change password</button></div></form>`);
  $('#pf').onsubmit = async e => {
    e.preventDefault();
    try { await api('/users/me/password', { method: 'POST', json: Object.fromEntries(new FormData(e.target)) }); logout(); toast('Password changed. Please sign in again.'); }
    catch (x) { toast(x.message, 1); }
  };
}

async function exportCsv() {
  const q = S.q, p = new URLSearchParams();
  ['status', 'priority', 'search'].forEach(k => q[k] && p.set(k, q[k]));
  try {
    const r = await fetch('/tickets/export.csv?' + p, { headers: { Authorization: 'Bearer ' + S.token } });
    if (!r.ok) throw new Error('Export failed (' + r.status + ')');
    const a = document.createElement('a'); a.href = URL.createObjectURL(await r.blob()); a.download = 'tickets.csv'; a.click(); URL.revokeObjectURL(a.href);
  } catch (x) { toast(x.message, 1); }
}

/* ---------- dashboard ---------- */
async function viewDashboard() {
  try {
    const d = await api('/dashboard/stats');
    const grp = (t, o) => `<div class="card"><h3>${t}</h3>${Object.entries(o).map(([k, v]) => `<div class="row"><span>${L(k)}</span><progress max="${d.total_tickets || 1}" value="${v}"></progress><b>${v}</b></div>`).join('')}</div>`;
    $('#main').innerHTML = `<div class="grid"><div class="card stat"><small>Total tickets</small><b>${d.total_tickets}</b></div>
    <div class="card stat"><small>Resolved or closed</small><b>${d.resolved_tickets}</b></div>
    <div class="card stat"><small>Overdue (SLA)</small><b>${d.overdue_tickets}</b></div>
    <div class="card stat"><small>Average resolution time</small><b>${d.avg_resolution_hours == null ? '—' : d.avg_resolution_hours.toFixed(1) + ' h'}</b></div></div>
    <div class="grid2">${grp('By status', d.by_status)}${grp('By priority', d.by_priority)}</div>`;
  } catch (x) { toast(x.message, 1); }
}

/* ---------- users (admin) ---------- */
async function viewUsers() {
  try {
    const d = await api('/users/?limit=100');
    $('#main').innerHTML = `<form id="uf" class="bar"><input name="full_name" placeholder="Full name" required><input name="email" type="email" placeholder="Email" required>
    <input name="password" type="password" placeholder="Password (8+ chars)" minlength="8" required><select name="role">${opts(RL, 'agent')}</select><button class="primary">Add user</button></form>
    <div class="tw"><table><thead><tr><th>#</th><th>Name</th><th>Email</th><th>Role</th><th>Active</th></tr></thead><tbody>${d.items.map(u => { const me = u.id === S.me.id; return `<tr><td>${u.id}</td><td>${esc(u.full_name)}</td><td>${esc(u.email)}</td>
    <td><select data-u="${u.id}" data-f="role" ${me ? 'disabled' : ''}>${opts(RL, u.role)}</select></td><td><input type="checkbox" data-u="${u.id}" data-f="is_active" ${u.is_active ? 'checked' : ''} ${me ? 'disabled' : ''}></td></tr>`; }).join('')}</tbody></table></div>
    <p class="hint">Showing ${d.items.length} of ${d.total} users.</p>`;
    $('#uf').onsubmit = async e => {
      e.preventDefault();
      try { await api('/auth/register', { method: 'POST', json: Object.fromEntries(new FormData(e.target)) }); toast('User created'); viewUsers(); }
      catch (x) { toast(x.message, 1); }
    };
    $('#main').onchange = async e => {
      const t = e.target, u = t.dataset.u; if (!u) return;
      try { await api('/users/' + u, { method: 'PATCH', json: { [t.dataset.f]: t.type === 'checkbox' ? t.checked : t.value } }); toast('User updated'); }
      catch (x) { toast(x.message, 1); viewUsers(); }
    };
  } catch (x) { toast(x.message, 1); }
}

/* ---------- system settings (admin) ---------- */
async function viewSettings() {
  try {
    const d = await api('/admin/settings/');
    $('#main').innerHTML = `<p class="hint">Changes apply immediately. Examples: <code>company_name</code>, <code>allow_employee_registration</code> (true/false), <code>max_open_tickets_per_employee</code>, <code>auto_assign_on_create</code> (true/false), <code>sla_hours_urgent|high|medium|low</code>.</p>
    <form id="sf" class="bar"><input name="key" placeholder="key (a-z, 0-9, _ . -)" required pattern="[a-z0-9][a-z0-9_.\\-]*"><input name="value" placeholder="Value" required><input name="description" placeholder="Description (optional)"><button class="primary">Add setting</button></form>
    <div class="tw"><table><thead><tr><th>Key</th><th>Value</th><th>Description</th><th></th></tr></thead><tbody>${d.map(x => `<tr><td><code>${esc(x.key)}</code></td>
    <td><input data-k="${esc(x.key)}" value="${esc(x.value)}"></td><td>${esc(x.description || '')}</td>
    <td><button data-sv="${esc(x.key)}">Save</button> <button class="danger" data-dl="${esc(x.key)}">Delete</button></td></tr>`).join('')}</tbody></table></div>`;
    $('#sf').onsubmit = async e => {
      e.preventDefault(); const f = Object.fromEntries(new FormData(e.target)); if (!f.description) delete f.description;
      try { await api('/admin/settings/', { method: 'POST', json: f }); toast('Setting added'); viewSettings(); } catch (x) { toast(x.message, 1); }
    };
    $('#main').onclick = async e => {
      const sv = e.target.dataset.sv, dl = e.target.dataset.dl;
      try {
        if (sv) {
          const inp = [...document.querySelectorAll('input[data-k]')].find(i => i.dataset.k === sv);
          await api('/admin/settings/' + encodeURIComponent(sv), { method: 'PATCH', json: { value: inp.value } });
          toast('Setting saved'); await loadPublic(); shell();
        } else if (dl && confirm('Delete setting "' + dl + '"? The built-in default will apply.')) {
          await api('/admin/settings/' + encodeURIComponent(dl), { method: 'DELETE' }); toast('Setting deleted'); viewSettings();
        }
      } catch (x) { toast(x.message, 1); }
    };
  } catch (x) { toast(x.message, 1); }
}

boot();
