<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>STREAM CORPORATION | SECURE ACCESS v1.0</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,300;14..32,400;14..32,500;14..32,600;14..32,700;14..32,800&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }

:root {
  --bg-deep: #05050a;
  --glass-surface: rgba(15, 15, 25, 0.65);
  --glass-stroke: rgba(255, 255, 255, 0.08);
  --accent-neon: #ef4444;
  --accent-glow: #ff5a5a;
  --green-neon: #22c55e;
  --orange-neon: #f97316;
  --blue-neon: #3b82f6;
  --text-primary: #f0f2fc;
  --text-secondary: #9ca3af;
  --text-dim: #6b7280;
}

body {
  background: var(--bg-deep);
  font-family: 'Inter', sans-serif;
  color: var(--text-primary);
  min-height: 100vh;
  font-size: 14px;
  overflow-x: hidden;
}

#particle-canvas {
  position: fixed;
  top: 0; left: 0;
  width: 100%; height: 100%;
  pointer-events: none;
  z-index: 0;
}

.sidebar, .card, .stat-card, .auth-box, .table-glass {
  background: var(--glass-surface);
  backdrop-filter: blur(14px);
  border: 1px solid var(--glass-stroke);
  border-radius: 28px;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.3);
  position: relative;
  z-index: 1;
}

/* AUTH GATE */
#auth-gate {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  position: relative;
  z-index: 2;
}

.auth-box {
  width: 100%;
  max-width: 440px;
  padding: 36px 30px;
  backdrop-filter: blur(24px);
  background: rgba(8, 8, 18, 0.82);
  border-radius: 40px;
  border: 1px solid rgba(239, 68, 68, 0.3);
  box-shadow: 0 0 60px rgba(239,68,68,0.08), 0 0 120px rgba(59,130,246,0.04);
}

.auth-logo {
  width: 72px;
  height: 72px;
  background: linear-gradient(135deg, rgba(239,68,68,0.25), rgba(0,0,0,0.3));
  border-radius: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  font-weight: 800;
  margin: 0 auto 22px;
  border: 1px solid rgba(239,68,68,0.6);
  box-shadow: 0 0 24px rgba(239,68,68,0.35), inset 0 0 20px rgba(239,68,68,0.08);
  animation: logoPulse 3s ease-in-out infinite;
}

@keyframes logoPulse {
  0%,100% { box-shadow: 0 0 24px rgba(239,68,68,0.35), inset 0 0 20px rgba(239,68,68,0.08); }
  50% { box-shadow: 0 0 40px rgba(239,68,68,0.55), inset 0 0 30px rgba(239,68,68,0.15); }
}

.auth-box h2 {
  font-size: 30px;
  font-weight: 800;
  text-align: center;
  letter-spacing: -0.5px;
}

.auth-gradient {
  background: linear-gradient(120deg, #ffffff 0%, #ef4444 40%, #ff8a8a 70%, #ffffff 100%);
  background-size: 200% auto;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: textShine 4s linear infinite;
  filter: drop-shadow(0 0 12px rgba(239,68,68,0.5));
}

@keyframes textShine {
  0% { background-position: 0% center; }
  100% { background-position: 200% center; }
}

.input-glow {
  background: rgba(0,0,0,0.55) !important;
  border: 1px solid rgba(255,255,255,0.09);
  border-radius: 20px;
  padding: 14px 18px;
  width: 100%;
  color: white;
  margin-bottom: 16px;
  backdrop-filter: blur(4px);
  transition: 0.2s;
  font-family: 'Inter', sans-serif;
  font-size: 14px;
}

.input-glow:focus {
  border-color: rgba(239,68,68,0.6);
  outline: none;
  box-shadow: 0 0 0 3px rgba(239,68,68,0.15), 0 0 12px rgba(239,68,68,0.1);
}

.btn-glass {
  width: 100%;
  background: linear-gradient(135deg, #dc2626, #7f1d1d);
  border: none;
  padding: 14px;
  border-radius: 40px;
  font-weight: 700;
  font-size: 14px;
  letter-spacing: 0.3px;
  color: white;
  cursor: pointer;
  transition: 0.2s;
  box-shadow: 0 4px 14px rgba(239,68,68,0.25);
}

.btn-glass:hover {
  transform: scale(0.98);
  box-shadow: 0 6px 20px rgba(239,68,68,0.4);
}

/* APP LAYOUT */
#app-layout {
  display: none;
  min-height: 100vh;
  position: relative;
  z-index: 1;
}

.sidebar {
  width: 280px;
  position: fixed;
  left: 0; top: 0;
  height: 100vh;
  border-radius: 0 32px 32px 0;
  backdrop-filter: blur(24px);
  background: rgba(5, 5, 12, 0.88);
  border-right: 1px solid rgba(239,68,68,0.15);
  display: flex;
  flex-direction: column;
  z-index: 10;
}

.brand {
  padding: 28px 24px;
  display: flex;
  gap: 14px;
  align-items: center;
  border-bottom: 1px solid rgba(255,255,255,0.07);
}

.brand-icon {
  width: 44px;
  height: 44px;
  background: linear-gradient(135deg, #ef4444, #7f1d1d);
  border-radius: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  font-weight: 800;
  box-shadow: 0 0 16px rgba(239,68,68,0.5);
}

.brand-title {
  font-size: 18px;
  font-weight: 800;
  background: linear-gradient(120deg, #fff 0%, #ef4444 50%, #fff 100%);
  background-size: 200% auto;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: textShine 5s linear infinite;
}

.nav-section {
  padding: 16px 0;
  flex: 1;
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 24px;
  width: 100%;
  background: transparent;
  border: none;
  color: var(--text-secondary);
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
  transition: 0.2s;
  border-left: 3px solid transparent;
}

.nav-item:hover { color: rgba(255,255,255,0.8); background: rgba(255,255,255,0.04); }
.nav-item.active {
  background: rgba(239,68,68,0.12);
  border-left: 3px solid var(--accent-neon);
  color: white;
}

.user-profile {
  padding: 20px 24px;
  border-top: 1px solid rgba(255,255,255,0.07);
  display: flex;
  gap: 14px;
  align-items: center;
}

.avatar {
  width: 42px;
  height: 42px;
  background: linear-gradient(145deg, #ef4444, #991b1b);
  border-radius: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  font-size: 16px;
}

.main-content {
  margin-left: 280px;
  padding: 30px 34px;
  position: relative;
  z-index: 1;
}

.page { display: none; animation: fadeSlide 0.3s ease; }
.page.active { display: block; }

@keyframes fadeSlide {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

.panel-section { display: none; }
.panel-section.active { display: block; }

.page-header {
  margin-bottom: 28px;
}
.page-header h1 {
  font-size: 26px;
  font-weight: 800;
  background: linear-gradient(120deg, #ffffff 0%, #ef4444 50%, #ffffff 100%);
  background-size: 200% auto;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: textShine 5s linear infinite;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4,1fr);
  gap: 18px;
  margin-bottom: 28px;
}

.stat-card {
  padding: 22px 20px;
  border-radius: 24px;
  background: rgba(10,10,20,0.7);
  border: 1px solid rgba(255,255,255,0.06);
}

.stat-number {
  font-size: 40px;
  font-weight: 800;
  font-family: 'Space Mono', monospace;
}
.stat-number.white { background: linear-gradient(135deg, #fff 0%, #aaa 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
.stat-number.green { color: #22c55e; text-shadow: 0 0 16px rgba(34,197,94,0.4); }
.stat-number.red { color: #ef4444; text-shadow: 0 0 16px rgba(239,68,68,0.4); }

.stat-label {
  font-size: 10px;
  letter-spacing: 1.5px;
  margin-top: 8px;
  color: var(--text-dim);
  text-transform: uppercase;
  font-weight: 600;
}

.card-grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 22px;
  margin-bottom: 28px;
}

.card {
  padding: 26px;
  border-radius: 28px;
  background: rgba(10,10,20,0.65);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.07);
}

.card h3 {
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 20px;
  color: rgba(255,255,255,0.9);
}

.table-glass {
  border-radius: 24px;
  overflow: hidden;
  margin-top: 16px;
  background: rgba(8,8,16,0.6);
  backdrop-filter: blur(12px);
}

table { width: 100%; border-collapse: collapse; }
th {
  text-align: left;
  padding: 16px 20px;
  background: rgba(0,0,0,0.4);
  color: var(--text-dim);
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
}
td {
  padding: 15px 20px;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  font-size: 13px;
}

.badge {
  padding: 5px 12px;
  border-radius: 40px;
  font-size: 10px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.badge-active {
  background: rgba(34,197,94,0.12);
  color: #4ade80;
  border: 1px solid rgba(34,197,94,0.25);
}
.badge-expired {
  background: rgba(239,68,68,0.12);
  color: #f87171;
  border: 1px solid rgba(239,68,68,0.25);
}

.btn-icon {
  background: none;
  border: 1px solid rgba(239,68,68,0.3);
  border-radius: 30px;
  padding: 5px 12px;
  color: #f87171;
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
  transition: 0.15s;
}
.btn-icon:hover {
  background: rgba(239,68,68,0.15);
  border-color: rgba(239,68,68,0.6);
}

.btn-refresh {
  background: rgba(239,68,68,0.1);
  border: 1px solid rgba(239,68,68,0.3);
  color: #f87171;
  padding: 10px 22px;
  border-radius: 40px;
  cursor: pointer;
  font-weight: 600;
  font-size: 13px;
}

.search-wrap {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 18px 0;
  gap: 16px;
}

.toast-gloss {
  position: fixed;
  bottom: 30px;
  right: 30px;
  background: rgba(5,5,12,0.92);
  backdrop-filter: blur(24px);
  padding: 14px 24px;
  border-radius: 60px;
  border: 1px solid rgba(239,68,68,0.4);
  border-left: 4px solid var(--accent-neon);
  z-index: 9999;
  transform: translateY(100px);
  opacity: 0;
  transition: 0.35s cubic-bezier(0.2,0.9,0.4,1.1);
  font-weight: 600;
  font-size: 13px;
}
.toast-gloss.show { transform: translateY(0); opacity: 1; }

.uid-mono {
  font-family: 'Space Mono', monospace;
  font-size: 12px;
  color: rgba(255,255,255,0.85);
}

.copy-btn {
  background: none;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  margin-left: 5px;
  font-size: 11px;
  padding: 2px 5px;
  border-radius: 6px;
}
.copy-btn:hover { color: white; background: rgba(255,255,255,0.08); }
</style>
</head>
<body>

<canvas id="particle-canvas"></canvas>

<!-- ACCESS GATE (Password Protected Page) -->
<div id="auth-gate">
  <div class="auth-box">
    <div class="auth-logo">
      <span style="font-weight:800; font-size:28px;">🔐</span>
    </div>
    <h2>SECURE <span class="auth-gradient">ACCESS</span></h2>
    <p style="text-align:center; font-size:11px; color:#6b7280; margin-bottom:14px;">// PASSWORD PROTECTED ZONE</p>
    <input type="password" id="access-password" class="input-glow" placeholder="Enter Access Password">
    <button class="btn-glass" onclick="verifyAccessPassword()">⟁ UNLOCK GATE</button>
    <div class="result-msg" id="access-login-err" style="margin-top:12px;"></div>
  </div>
</div>

<!-- APP LAYOUT (After Password Verification) -->
<div id="app-layout">
  <div class="sidebar">
    <div class="brand">
      <div class="brand-icon"><span style="font-weight:800; font-size:18px;">🔐</span></div>
      <div>
        <div class="brand-title">STREAM CORP</div>
        <span style="font-size:10px; color:#6b7280;">1-DAY UID ACCESS</span>
      </div>
    </div>
    <div class="nav-section">
      <button class="nav-item active" onclick="switchAccessTab('uids')">
        <span class="nav-icon">🎮</span> MY UIDs
      </button>
      <button class="nav-item" onclick="doAccessLogout()">
        <span class="nav-icon">🚪</span> EXIT
      </button>
    </div>
    <div class="user-profile">
      <div class="avatar" id="access-avatar">U</div>
      <div>
        <div id="access-user" style="font-weight:700; font-size:14px;">Access User</div>
        <div style="font-size:11px; color:#22c55e; font-weight:600;">1-Day Mode</div>
      </div>
    </div>
  </div>

  <div class="main-content">
    <!-- UIDs TAB -->
    <div id="access-tab-uids" class="panel-section active">
      <div class="page-header">
        <h1>🎮 1-DAY UID GENERATOR</h1>
        <p>CREATE UIDs WITH 1 DAY VALIDITY ONLY</p>
      </div>
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-number white" id="acc-total">—</div>
          <div class="stat-label">Total UIDs</div>
        </div>
        <div class="stat-card">
          <div class="stat-number green" id="acc-active">—</div>
          <div class="stat-label">Active</div>
        </div>
        <div class="stat-card">
          <div class="stat-number red" id="acc-expired">—</div>
          <div class="stat-label">Expired</div>
        </div>
      </div>

      <div class="card-grid-2">
        <div class="card">
          <h3>➕ CREATE 1-DAY UID</h3>
          <input type="text" id="acc-uid" class="input-glow" placeholder="User ID (e.g. 123456789)">
          <input type="text" id="acc-name" class="input-glow" placeholder="Player Name">
          <div style="background:rgba(34,197,94,0.1); border:1px solid rgba(34,197,94,0.3); border-radius:20px; padding:12px; margin-bottom:16px; text-align:center;">
            <span style="color:#22c55e; font-weight:700;">⏱️ 1 DAY ONLY</span>
            <span style="color:#6b7280; font-size:12px; margin-left:8px;">(Fixed - No other options)</span>
          </div>
          <button class="btn-glass" onclick="accessAddUID()">💾 CREATE 1-DAY LICENSE</button>
          <div class="result-msg" id="acc-add-result"></div>
        </div>
        <div class="card">
          <h3>⚙️ MANAGE UID</h3>
          <input type="text" id="acc-rm-uid" class="input-glow" placeholder="UID to remove">
          <button class="btn-glass" style="background:linear-gradient(135deg,#7f1d1d,#450a0a);" onclick="accessRemoveUID()">🗑 REMOVE UID</button>
          <div class="result-msg" id="acc-rm-result"></div>
        </div>
      </div>

      <div class="search-wrap">
        <button class="btn-refresh" onclick="accessLoadUIDs()">⟳ REFRESH</button>
        <input type="text" id="acc-search" class="input-glow" style="width:280px; margin:0;" placeholder="🔍 Filter UID or Name">
      </div>

      <div class="table-glass">
        <table>
          <thead>
            <tr><th>UID</th><th>NAME</th><th>VALIDITY</th><th>STATUS</th><th>EXPIRES</th><th>DAYS LEFT</th><th>ACTION</th></tr>
          </thead>
          <tbody id="access-uid-tbody">
            <tr><td colspan="7" style="text-align:center; color:#6b7280; padding:40px;">Enter password to access...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<div id="toastMsg" class="toast-gloss"></div>

<script>
// PARTICLE SYSTEM
(function(){
  const canvas = document.getElementById('particle-canvas');
  const ctx = canvas.getContext('2d');
  let W, H, particles = [], mouse = {x: -999, y: -999};
  function resize(){ W = canvas.width = window.innerWidth; H = canvas.height = window.innerHeight; }
  resize();
  window.addEventListener('resize', resize);
  window.addEventListener('mousemove', e => { mouse.x = e.clientX; mouse.y = e.clientY; });
  const COLORS = ['rgba(239,68,68,', 'rgba(59,130,246,', 'rgba(139,92,246,', 'rgba(249,115,22,', 'rgba(34,197,94,'];
  for(let i = 0; i < 100; i++) particles.push({ x: Math.random() * W, y: Math.random() * H, vx: (Math.random() - 0.5) * 0.3, vy: (Math.random() - 0.5) * 0.3, r: Math.random() * 1.5 + 0.3, alpha: Math.random() * 0.5 + 0.1, color: COLORS[Math.floor(Math.random() * COLORS.length)], pulse: Math.random() * Math.PI * 2 });
  function draw(){
    ctx.clearRect(0, 0, W, H);
    particles.forEach(p => { p.pulse = (p.pulse || 0) + 0.01; const a = p.alpha * (0.7 + 0.3 * Math.sin(p.pulse)); ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI*2); ctx.fillStyle = p.color + a + ')'; ctx.fill(); p.x += p.vx; if(p.x < 0) p.x = W; if(p.x > W) p.x = 0; if(p.y < 0) p.y = H; if(p.y > H) p.y = 0; });
    requestAnimationFrame(draw);
  }
  draw();
})();

// STORAGE KEYS
let ACCESS_SESSION = { password: null, uid: null };
let currentAccessUIDs = [];

function showToast(msg){
  const t = document.getElementById('toastMsg');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2500);
}

function showResult(elId, msg, type){
  const el = document.getElementById(elId);
  if(el) { el.innerHTML = `<span style="color:${type==='success'?'#4ade80':'#f87171'};">${msg}</span>`; setTimeout(() => el.innerHTML = '', 3000); }
}

// ========== ACCESS PASSWORD VERIFICATION ==========
// Predefined passwords (Master Admin can manage these)
let accessPasswords = [
  { id: 'p1', password: 'STREAM2025', note: 'VIP Access', created: new Date().toISOString(), expiry: null },
  { id: 'p2', password: 'DEMO123', note: 'Demo User', created: new Date().toISOString(), expiry: null }
];

// Load from localStorage
function loadAccessPasswords(){
  const stored = localStorage.getItem('stream_access_passwords');
  if(stored) {
    try{
      accessPasswords = JSON.parse(stored);
    }catch(e){}
  } else {
    saveAccessPasswords();
  }
}

function saveAccessPasswords(){
  localStorage.setItem('stream_access_passwords', JSON.stringify(accessPasswords));
}

// Verify entered password
function verifyAccessPassword(){
  const entered = document.getElementById('access-password').value.trim();
  if(!entered) { showResult('access-login-err', 'Enter password', 'error'); return; }
  
  const valid = accessPasswords.find(p => p.password === entered);
  if(valid){
    ACCESS_SESSION.password = entered;
    ACCESS_SESSION.uid = 'access_' + Date.now();
    localStorage.setItem('access_session', JSON.stringify({ password: entered, uid: ACCESS_SESSION.uid }));
    enterAccessPanel();
    showToast('Access granted! You can create 1-day UIDs only.');
  } else {
    showResult('access-login-err', 'Invalid password!', 'error');
  }
}

function enterAccessPanel(){
  document.getElementById('auth-gate').style.display = 'none';
  document.getElementById('app-layout').style.display = 'flex';
  document.getElementById('access-avatar').textContent = 'U';
  document.getElementById('access-user').textContent = 'Access User';
  accessLoadUIDs();
}

function doAccessLogout(){
  ACCESS_SESSION = { password: null, uid: null };
  localStorage.removeItem('access_session');
  document.getElementById('app-layout').style.display = 'none';
  document.getElementById('auth-gate').style.display = 'flex';
  document.getElementById('access-password').value = '';
}

function switchAccessTab(tab){
  document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.panel-section').forEach(s => s.classList.remove('active'));
  if(tab === 'uids'){
    document.getElementById('access-tab-uids').classList.add('active');
    document.querySelector('.nav-item').classList.add('active');
  }
}

// ========== 1-DAY UID MANAGEMENT (LocalStorage based) ==========
// Each UID has: uid, name, createdAt, expiresAt (1 day from creation)
function loadAccessUIDsFromStorage(){
  const key = `access_uids_${ACCESS_SESSION.password}`;
  const stored = localStorage.getItem(key);
  if(stored){
    try{
      currentAccessUIDs = JSON.parse(stored);
    }catch(e){ currentAccessUIDs = []; }
  } else {
    currentAccessUIDs = [];
  }
  // Auto-expire check
  const now = new Date();
  let changed = false;
  currentAccessUIDs = currentAccessUIDs.filter(u => {
    if(new Date(u.expiresAt) > now) return true;
    changed = true;
    return false;
  });
  if(changed) saveAccessUIDsToStorage();
}

function saveAccessUIDsToStorage(){
  const key = `access_uids_${ACCESS_SESSION.password}`;
  localStorage.setItem(key, JSON.stringify(currentAccessUIDs));
}

function calculateRemaining(expiryDateStr){
  const exp = new Date(expiryDateStr);
  const now = new Date();
  const diffMs = exp - now;
  if(diffMs <= 0) return 0;
  return Math.ceil(diffMs / (1000 * 60 * 60 * 24));
}

function formatExpiry(expiryDateStr){
  const d = new Date(expiryDateStr);
  return d.toLocaleDateString('en-GB', {day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit'});
}

function renderDaysLeftBadge(remaining){
  if(remaining <= 0) return `<span style="color:#f87171; font-weight:700;">EXPIRED</span>`;
  if(remaining === 1) return `<span style="color:#f97316; font-weight:700;">⚡ ${remaining}d left</span>`;
  return `<span style="color:#4ade80;">✓ ${remaining}d</span>`;
}

function renderAccessTable(){
  const tb = document.getElementById('access-uid-tbody');
  if(!currentAccessUIDs.length){
    tb.innerHTML = '<tr><td colspan="7" style="text-align:center; color:#6b7280; padding:40px;">✨ No UIDs created yet. Create your first 1-day UID! ✨</td></tr>';
    return;
  }
  tb.innerHTML = currentAccessUIDs.map(u => {
    const remaining = calculateRemaining(u.expiresAt);
    const statusBadge = remaining > 0 ? '<span class="badge badge-active">● ACTIVE</span>' : '<span class="badge badge-expired">✖ EXPIRED</span>';
    return `<tr>
      <td><span class="uid-mono">${u.uid}</span><button class="copy-btn" onclick="navigator.clipboard.writeText('${u.uid}');showToast('Copied!')">📋</button></td>
      <td style="font-weight:600;">${u.name}</td>
      <td><span style="color:#22c55e; font-weight:700;">1 DAY</span></td>
      <td>${statusBadge}</td>
      <td style="font-size:12px;">${formatExpiry(u.expiresAt)}</td>
      <td>${renderDaysLeftBadge(remaining)}</td>
      <td><button class="btn-icon" onclick="accessDeleteUID('${u.uid}')">DELETE</button></td>
    </tr>`;
  }).join('');
  updateAccessStats();
}

function updateAccessStats(){
  const total = currentAccessUIDs.length;
  let active = 0, expired = 0;
  currentAccessUIDs.forEach(u => {
    if(calculateRemaining(u.expiresAt) > 0) active++;
    else expired++;
  });
  document.getElementById('acc-total').textContent = total;
  document.getElementById('acc-active').textContent = active;
  document.getElementById('acc-expired').textContent = expired;
}

function accessLoadUIDs(){
  loadAccessUIDsFromStorage();
  renderAccessTable();
}

function accessAddUID(){
  const uid = document.getElementById('acc-uid').value.trim();
  const name = document.getElementById('acc-name').value.trim() || 'Player';
  if(!uid){
    showToast('UID is required!', 'error');
    showResult('acc-add-result', '❌ UID required', 'error');
    return;
  }
  // Check duplicate
  if(currentAccessUIDs.some(u => u.uid === uid)){
    showToast('UID already exists!', 'error');
    showResult('acc-add-result', '❌ UID already exists', 'error');
    return;
  }
  
  // Create with EXACTLY 1 DAY validity
  const now = new Date();
  const expiresAt = new Date(now.getTime() + 24 * 60 * 60 * 1000); // 1 day exactly
  
  const newUID = {
    uid: uid,
    name: name,
    createdAt: now.toISOString(),
    expiresAt: expiresAt.toISOString(),
    days: 1
  };
  
  currentAccessUIDs.push(newUID);
  saveAccessUIDsToStorage();
  renderAccessTable();
  
  document.getElementById('acc-uid').value = '';
  document.getElementById('acc-name').value = '';
  showToast(`✅ 1-day UID created for ${name}! Expires in 24 hours.`);
  showResult('acc-add-result', '✓ 1-day UID created!', 'success');
}

function accessRemoveUID(){
  const uid = document.getElementById('acc-rm-uid').value.trim();
  if(!uid){
    showToast('Enter UID to remove', 'error');
    return;
  }
  accessDeleteUID(uid);
  document.getElementById('acc-rm-uid').value = '';
}

function accessDeleteUID(uid){
  const exists = currentAccessUIDs.find(u => u.uid === uid);
  if(!exists){
    showToast('UID not found', 'error');
    return;
  }
  currentAccessUIDs = currentAccessUIDs.filter(u => u.uid !== uid);
  saveAccessUIDsToStorage();
  renderAccessTable();
  showToast(`🗑 UID ${uid} removed`);
  showResult('acc-rm-result', '✓ UID deleted', 'success');
}

// Filter function
document.getElementById('acc-search')?.addEventListener('input', (e) => {
  const q = e.target.value.toLowerCase();
  const tb = document.getElementById('access-uid-tbody');
  const filtered = currentAccessUIDs.filter(u => u.uid.toLowerCase().includes(q) || u.name.toLowerCase().includes(q));
  if(filtered.length === 0){
    tb.innerHTML = '<tr><td colspan="7" style="text-align:center; color:#6b7280; padding:40px;">No matching UIDs</td></tr>';
    return;
  }
  tb.innerHTML = filtered.map(u => {
    const remaining = calculateRemaining(u.expiresAt);
    const statusBadge = remaining > 0 ? '<span class="badge badge-active">● ACTIVE</span>' : '<span class="badge badge-expired">✖ EXPIRED</span>';
    return `<tr>
      <td><span class="uid-mono">${u.uid}</span><button class="copy-btn" onclick="navigator.clipboard.writeText('${u.uid}');showToast('Copied!')">📋</button></td>
      <td>${u.name}</td>
      <td><span style="color:#22c55e;">1 DAY</span></td>
      <td>${statusBadge}</td>
      <td>${formatExpiry(u.expiresAt)}</td>
      <td>${renderDaysLeftBadge(remaining)}</td>
      <td><button class="btn-icon" onclick="accessDeleteUID('${u.uid}')">DELETE</button></td>
    </tr>`;
  }).join('');
});

// ========== MASTER ADMIN PASSWORD MANAGEMENT (Hidden but accessible via console or separate panel) ==========
// For full password management, master admin can use browser console or we add a hidden section
// Since original requirement says "পাসওয়াড আমি ক্রিয়েট করতে পারবো এবং ডিলিট করতে পারবো" - adding a secret admin area
// Press 'Ctrl+Shift+M' to open Master Password Manager (only for main admin)
let masterAdminLoggedIn = false;
const MASTER_KEY = 'STREAM_MASTER_2025';

function showPasswordManager(){
  const pwd = prompt('Master Admin Key Required:');
  if(pwd === MASTER_KEY){
    masterAdminLoggedIn = true;
    let action = prompt('Password Manager:\n1. Create New Password\n2. Delete Password\n3. List Passwords\nEnter number:');
    if(action === '1'){
      const newPwd = prompt('Enter new access password:');
      const note = prompt('Enter note (optional):');
      if(newPwd){
        accessPasswords.push({ id: 'p'+Date.now(), password: newPwd, note: note || '', created: new Date().toISOString(), expiry: null });
        saveAccessPasswords();
        alert(`✅ Password "${newPwd}" created successfully!`);
      }
    } else if(action === '2'){
      const list = accessPasswords.map((p,i) => `${i+1}. ${p.password} (${p.note || 'no note'})`).join('\n');
      const idx = prompt(`Current passwords:\n${list}\n\nEnter number to delete:`);
      if(idx && !isNaN(idx)){
        const i = parseInt(idx)-1;
        if(accessPasswords[i]){
          const removed = accessPasswords[i].password;
          accessPasswords.splice(i,1);
          saveAccessPasswords();
          alert(`🗑 Deleted password: ${removed}`);
        } else alert('Invalid number');
      }
    } else if(action === '3'){
      alert(accessPasswords.map(p => `🔐 ${p.password} - ${p.note || 'no note'}`).join('\n'));
    } else alert('Invalid option');
    masterAdminLoggedIn = false;
  } else {
    alert('Invalid Master Key!');
  }
}

// Hotkey for master admin: Ctrl+Shift+M
document.addEventListener('keydown', (e) => {
  if(e.ctrlKey && e.shiftKey && e.key === 'M'){
    e.preventDefault();
    showPasswordManager();
  }
});

// Auto-load saved session
(function init(){
  loadAccessPasswords();
  const savedSession = localStorage.getItem('access_session');
  if(savedSession){
    try{
      const ss = JSON.parse(savedSession);
      if(ss.password && accessPasswords.some(p => p.password === ss.password)){
        ACCESS_SESSION = ss;
        enterAccessPanel();
      }
    }catch(e){}
  }
})();
</script>

<!-- Master Admin Instruction Panel (small note) -->
<div style="position:fixed; bottom:15px; left:15px; z-index:9999; background:rgba(0,0,0,0.6); backdrop-filter:blur(8px); padding:6px 12px; border-radius:20px; font-size:10px; color:#6b7280; pointer-events:none;">
  Master Admin: <kbd style="background:#222; padding:2px 6px; border-radius:6px;">Ctrl+Shift+M</kbd> to manage passwords
</div>

</body>
</html>
