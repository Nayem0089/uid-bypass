# User Management App — Render Deployment Guide

## 📁 Files
| File | Purpose |
|------|---------|
| `app.py` | Flask backend |
| `requirements.txt` | Python dependencies |
| `Procfile` | Tells Render how to start the app |
| `render.yaml` | Render Blueprint config (auto-setup) |
| `templates/index.html` | Frontend UI |

---

## 🚀 Deploy to Render (Step-by-Step)

### Step 1 — Push to GitHub
1. Create a new GitHub repo (e.g. `user-management-app`)
2. Upload all these files into it

### Step 2 — Connect to Render
1. Go to [https://render.com](https://render.com) and sign in
2. Click **"New +"** → **"Web Service"**
3. Connect your GitHub repo
4. Render will auto-detect settings from `render.yaml`

### Step 3 — Add Persistent Disk (important!)
> Without this, your SQLite database resets on every deploy.

1. In Render dashboard → your service → **"Disks"**
2. Click **"Add Disk"**
3. Set:
   - **Mount Path:** `/data`
   - **Size:** 1 GB (free tier allows this)

### Step 4 — Deploy
- Click **"Create Web Service"**
- Wait ~2 minutes for the build to finish
- Your app will be live at: `https://your-app-name.onrender.com`

---

## ⚙️ Environment Variables
No extra env vars needed. Render auto-assigns `PORT`.

## 🔧 Local Testing
```bash
pip install flask gunicorn
python app.py
# Open http://localhost:5000
```
