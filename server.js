/**
 * STREAM CORP Admin Panel - Backend API
 * Node.js + Express, JSON file storage (db.json)
 *
 * Run:
 *   npm install
 *   npm start
 *
 * Default Master Key: admin123   (change it from Settings tab after first login)
 */
const express = require('express');
const cors = require('cors');
const fs = require('fs');
const path = require('path');

const app = express();
const DB_FILE = path.join(__dirname, 'db.json');
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public'))); // serves index.html at /

// ---------- DB helpers ----------
const DEFAULT_DB = { adminKey: 'admin123', admins: [], licenses: [], subadmins: [], operators: [] };

function readDB() {
  try {
    if (!fs.existsSync(DB_FILE)) {
      // db.json missing on this deploy (common on fresh Render deploys) — auto-create it
      fs.writeFileSync(DB_FILE, JSON.stringify(DEFAULT_DB, null, 2));
      return JSON.parse(JSON.stringify(DEFAULT_DB));
    }
    const raw = fs.readFileSync(DB_FILE, 'utf8');
    if (!raw || !raw.trim()) {
      fs.writeFileSync(DB_FILE, JSON.stringify(DEFAULT_DB, null, 2));
      return JSON.parse(JSON.stringify(DEFAULT_DB));
    }
    return JSON.parse(raw);
  } catch (e) {
    console.error('readDB failed, resetting db.json:', e.message);
    fs.writeFileSync(DB_FILE, JSON.stringify(DEFAULT_DB, null, 2));
    return JSON.parse(JSON.stringify(DEFAULT_DB));
  }
}
function writeDB(db) {
  fs.writeFileSync(DB_FILE, JSON.stringify(db, null, 2));
}
function addDays(date, days) {
  const d = new Date(date);
  d.setDate(d.getDate() + days);
  return d;
}
function addHours(date, hours) {
  const d = new Date(date);
  d.setHours(d.getHours() + hours);
  return d;
}
function isExpired(dateStr) {
  if (!dateStr) return false;
  return new Date(dateStr).getTime() < Date.now();
}

// ================= MASTER ADMIN =================

// Verify master key
app.post('/admin/verify', (req, res) => {
  const { admin_key } = req.body;
  const db = readDB();
  if (admin_key && admin_key === db.adminKey) {
    return res.json({ status: 'success' });
  }
  return res.status(401).json({ message: 'Invalid Master Key' });
});

// Change master key
app.post('/admin/change-key', (req, res) => {
  const { admin_key, new_key } = req.body;
  const db = readDB();
  if (admin_key !== db.adminKey) return res.status(401).json({ message: 'Current key is incorrect' });
  if (!new_key || new_key.length < 6) return res.status(400).json({ message: 'New key must be at least 6 characters' });
  db.adminKey = new_key;
  writeDB(db);
  res.json({ status: 'success' });
});

// Create extra admin login (optional multi-admin - stored but not required for auth flow above)
app.post('/admin/create-admin', (req, res) => {
  const { admin_key, username, password } = req.body;
  const db = readDB();
  if (admin_key !== db.adminKey) return res.status(401).json({ message: 'Invalid Master Key' });
  if (!username || !password) return res.status(400).json({ message: 'Username and password required' });
  if (db.admins.find(a => a.username === username)) return res.status(400).json({ message: 'Admin already exists' });
  db.admins.push({ username, password });
  writeDB(db);
  res.json({ status: 'success' });
});

// ---- UID Vault (Main Admin) ----

app.get('/admin/list', (req, res) => {
  const { admin_key } = req.query;
  const db = readDB();
  if (admin_key !== db.adminKey) return res.status(401).json({ message: 'Invalid Master Key' });
  res.json({ status: 'success', licenses: db.licenses });
});

app.post('/admin/create', (req, res) => {
  const { admin_key, uid, name, days, hours, duration_hours } = req.body;
  const db = readDB();
  if (admin_key !== db.adminKey) return res.status(401).json({ message: 'Invalid Master Key' });
  if (!uid) return res.status(400).json({ message: 'UID is required' });
  if (db.licenses.find(l => String(l.uid) === String(uid))) {
    return res.status(400).json({ message: 'UID already exists' });
  }
  const now = new Date();
  const expires_at = duration_hours
    ? addHours(now, duration_hours).toISOString()
    : addDays(now, parseInt(days) || 30).toISOString();

  db.licenses.push({
    uid: String(uid),
    name: name || 'Player',
    days: duration_hours ? 1 : (parseInt(days) || 30),
    created_by: 'main_admin',
    created_at: now.toISOString(),
    expires_at
  });
  writeDB(db);
  res.json({ status: 'success', uid, expires_at });
});

app.post('/admin/update', (req, res) => {
  const { admin_key, uid, days } = req.body;
  const db = readDB();
  if (admin_key !== db.adminKey) return res.status(401).json({ message: 'Invalid Master Key' });
  const lic = db.licenses.find(l => String(l.uid) === String(uid));
  if (!lic) return res.status(404).json({ message: 'UID not found' });
  const base = isExpired(lic.expires_at) ? new Date() : new Date(lic.expires_at);
  lic.expires_at = addDays(base, parseInt(days) || 0).toISOString();
  writeDB(db);
  res.json({ status: 'success', uid, expires_at: lic.expires_at });
});

app.post('/admin/revoke', (req, res) => {
  const { admin_key, uid } = req.body;
  const db = readDB();
  if (admin_key !== db.adminKey) return res.status(401).json({ message: 'Invalid Master Key' });
  const before = db.licenses.length;
  db.licenses = db.licenses.filter(l => String(l.uid) !== String(uid));
  if (db.licenses.length === before) return res.status(404).json({ message: 'UID not found' });
  writeDB(db);
  res.json({ status: 'success' });
});

// ---- Resellers (Sub Admins) ----

app.post('/admin/create-subadmin', (req, res) => {
  const { admin_key, username, password, note } = req.body;
  const db = readDB();
  if (admin_key !== db.adminKey) return res.status(401).json({ message: 'Invalid Master Key' });
  if (!username || !password) return res.status(400).json({ message: 'Username and password required' });
  if (db.subadmins.find(s => s.username === username)) return res.status(400).json({ message: 'Reseller already exists' });
  db.subadmins.push({ username, password, note: note || '', credits: 0 });
  writeDB(db);
  res.json({ status: 'success' });
});

app.get('/admin/list-subadmins', (req, res) => {
  const { admin_key } = req.query;
  const db = readDB();
  if (admin_key !== db.adminKey) return res.status(401).json({ message: 'Invalid Master Key' });
  const safe = db.subadmins.map(s => ({ username: s.username, note: s.note, credits: s.credits }));
  res.json({ status: 'success', subadmins: safe });
});

app.post('/admin/delete-subadmin', (req, res) => {
  const { admin_key, username } = req.body;
  const db = readDB();
  if (admin_key !== db.adminKey) return res.status(401).json({ message: 'Invalid Master Key' });
  const before = db.subadmins.length;
  db.subadmins = db.subadmins.filter(s => s.username !== username);
  if (db.subadmins.length === before) return res.status(404).json({ message: 'Reseller not found' });
  writeDB(db);
  res.json({ status: 'success' });
});

app.post('/admin/give-credits', (req, res) => {
  const { admin_key, username, amount } = req.body;
  const db = readDB();
  if (admin_key !== db.adminKey) return res.status(401).json({ message: 'Invalid Master Key' });
  const sub = db.subadmins.find(s => s.username === username);
  if (!sub) return res.status(404).json({ message: 'Reseller not found' });
  const amt = parseInt(amount);
  if (!amt || amt < 1) return res.status(400).json({ message: 'Invalid amount' });
  sub.credits = (sub.credits || 0) + amt;
  writeDB(db);
  res.json({ status: 'success', new_credits: sub.credits });
});

// ---- Operators (limited: add-only, time-boxed accounts) ----

app.post('/admin/create-operator', (req, res) => {
  const { admin_key, username, password, expiry_days, max_days } = req.body;
  const db = readDB();
  if (admin_key !== db.adminKey) return res.status(401).json({ message: 'Invalid Master Key' });
  if (!username || !password) return res.status(400).json({ message: 'Username and password required' });
  if (db.operators.find(o => o.username === username)) {
    return res.status(400).json({ message: 'Operator already exists' });
  }
  const expires_at = addDays(new Date(), parseInt(expiry_days) || 30).toISOString();
  const operator = {
    username,
    password,
    expires_at,
    max_days: parseInt(max_days) || 30,
    uids_added: 0
  };
  db.operators.push(operator);
  writeDB(db);
  res.json({ status: 'success', username, expires_at, max_days: operator.max_days });
});

app.get('/admin/list-operators', (req, res) => {
  const { admin_key } = req.query;
  const db = readDB();
  if (admin_key !== db.adminKey) return res.status(401).json({ message: 'Invalid Master Key' });
  const safe = db.operators.map(o => ({
    username: o.username,
    expires_at: o.expires_at,
    max_days: o.max_days,
    uids_added: o.uids_added || 0
  }));
  res.json({ status: 'success', operators: safe });
});

app.post('/admin/delete-operator', (req, res) => {
  const { admin_key, username } = req.body;
  const db = readDB();
  if (admin_key !== db.adminKey) return res.status(401).json({ message: 'Invalid Master Key' });
  const before = db.operators.length;
  db.operators = db.operators.filter(o => o.username !== username);
  if (db.operators.length === before) return res.status(404).json({ message: 'Operator not found' });
  writeDB(db);
  res.json({ status: 'success' });
});

// ================= RESELLER (SUB ADMIN) =================

function findSubadmin(db, username, password) {
  return db.subadmins.find(s => s.username === username && s.password === password);
}

app.post('/subadmin/login', (req, res) => {
  const { username, password } = req.body;
  const db = readDB();
  const sub = findSubadmin(db, username, password);
  if (!sub) return res.status(401).json({ message: 'Invalid username or password' });
  res.json({ status: 'success' });
});

app.get('/subadmin/credits', (req, res) => {
  const { username, password } = req.query;
  const db = readDB();
  const sub = findSubadmin(db, username, password);
  if (!sub) return res.status(401).json({ message: 'Invalid credentials' });
  res.json({ status: 'success', credits: sub.credits || 0 });
});

app.get('/subadmin/list', (req, res) => {
  const { username, password } = req.query;
  const db = readDB();
  const sub = findSubadmin(db, username, password);
  if (!sub) return res.status(401).json({ message: 'Invalid credentials' });
  const mine = db.licenses.filter(l => l.created_by === username);
  res.json({ status: 'success', licenses: mine });
});

app.post('/subadmin/create', (req, res) => {
  const { username, password, uid, name, days, hours, duration_hours } = req.body;
  const db = readDB();
  const sub = findSubadmin(db, username, password);
  if (!sub) return res.status(401).json({ message: 'Invalid credentials' });
  if ((sub.credits || 0) < 1) return res.status(400).json({ message: 'No credit left. Contact Main Admin.' });
  if (!uid) return res.status(400).json({ message: 'UID is required' });
  if (db.licenses.find(l => String(l.uid) === String(uid))) {
    return res.status(400).json({ message: 'UID already exists' });
  }
  const now = new Date();
  const expires_at = duration_hours
    ? addHours(now, duration_hours).toISOString()
    : addDays(now, parseInt(days) || 30).toISOString();

  db.licenses.push({
    uid: String(uid),
    name: name || 'Player',
    days: duration_hours ? 1 : (parseInt(days) || 30),
    created_by: username,
    created_role: 'reseller',
    created_at: now.toISOString(),
    expires_at
  });
  sub.credits = (sub.credits || 0) - 1;
  writeDB(db);
  res.json({ status: 'success', uid, expires_at, remaining_credits: sub.credits });
});

app.post('/subadmin/update', (req, res) => {
  const { username, password, uid, days } = req.body;
  const db = readDB();
  const sub = findSubadmin(db, username, password);
  if (!sub) return res.status(401).json({ message: 'Invalid credentials' });
  const lic = db.licenses.find(l => String(l.uid) === String(uid) && l.created_by === username);
  if (!lic) return res.status(404).json({ message: 'UID not found in your account' });
  const base = isExpired(lic.expires_at) ? new Date() : new Date(lic.expires_at);
  lic.expires_at = addDays(base, parseInt(days) || 0).toISOString();
  writeDB(db);
  res.json({ status: 'success', uid, expires_at: lic.expires_at });
});

app.post('/subadmin/revoke', (req, res) => {
  const { username, password, uid } = req.body;
  const db = readDB();
  const sub = findSubadmin(db, username, password);
  if (!sub) return res.status(401).json({ message: 'Invalid credentials' });
  const before = db.licenses.length;
  db.licenses = db.licenses.filter(l => !(String(l.uid) === String(uid) && l.created_by === username));
  if (db.licenses.length === before) return res.status(404).json({ message: 'UID not found in your account' });
  writeDB(db);
  res.json({ status: 'success' });
});

// ================= OPERATOR (add-only, time-boxed) =================

function findOperator(db, username, password) {
  return db.operators.find(o => o.username === username && o.password === password);
}

app.post('/operator/login', (req, res) => {
  const { username, password } = req.body;
  const db = readDB();
  const op = findOperator(db, username, password);
  if (!op) return res.status(401).json({ message: 'Invalid username or password' });
  if (isExpired(op.expires_at)) return res.status(401).json({ message: 'Your account has expired. Contact Main Admin.' });
  res.json({ status: 'success', max_days: op.max_days, expires_at: op.expires_at });
});

app.get('/operator/list', (req, res) => {
  const { username, password } = req.query;
  const db = readDB();
  const op = findOperator(db, username, password);
  if (!op) return res.status(401).json({ message: 'Invalid credentials' });
  if (isExpired(op.expires_at)) return res.status(401).json({ message: 'Your account has expired.' });
  const mine = db.licenses.filter(l => l.created_by === username);
  res.json({ status: 'success', licenses: mine });
});

app.post('/operator/create', (req, res) => {
  const { username, password, uid, name, days, hours, duration_hours } = req.body;
  const db = readDB();
  const op = findOperator(db, username, password);
  if (!op) return res.status(401).json({ message: 'Invalid credentials' });
  if (isExpired(op.expires_at)) return res.status(401).json({ message: 'Your account has expired. Contact Main Admin.' });
  if (!uid) return res.status(400).json({ message: 'UID is required' });

  const reqDays = duration_hours ? 1 : (parseInt(days) || 1);
  if (reqDays > op.max_days) {
    return res.status(400).json({ message: `Max ${op.max_days} days allowed for your account` });
  }
  if (db.licenses.find(l => String(l.uid) === String(uid))) {
    return res.status(400).json({ message: 'UID already exists' });
  }

  const now = new Date();
  const expires_at = duration_hours
    ? addHours(now, duration_hours).toISOString()
    : addDays(now, reqDays).toISOString();

  db.licenses.push({
    uid: String(uid),
    name: name || 'Player',
    days: reqDays,
    created_by: username,
    created_role: 'operator',
    created_at: now.toISOString(),
    expires_at
  });
  op.uids_added = (op.uids_added || 0) + 1;
  writeDB(db);
  res.json({ status: 'success', uid, expires_at });
});

// ================= START =================
app.listen(PORT, () => {
  console.log(`STREAM CORP backend is running (port ${PORT})`);
  console.log(`Default Master Key: admin123 (change it from the Settings tab)`);
});
