import os
import requests
import threading
import time
# pyrefly: ignore [missing-import]
from flask import Flask, request, jsonify, render_template
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from pymongo import MongoClient
from datetime import datetime, timedelta

load_dotenv()

app = Flask(__name__)

# CONFIG
UID_API_BASE   = os.environ.get("UID_API_BASE", "https://uid.syntaxcorporation.online")
ADMIN_KEY      = os.environ.get("ADMIN_KEY",    "changeme_admin_key")
SELF_URL       = os.environ.get("SELF_URL",     "").rstrip("/")   # ← trailing slash সরানো হয়েছে

# MONGODB SETUP
MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://NAYEM:1122@cluster0.ywmyozb.mongodb.net/?appName=Cluster0")

try:
    mongo_client = MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=5000,
        tls=True,
        tlsAllowInvalidCertificates=True,
        connectTimeoutMS=10000,
        socketTimeoutMS=10000,
    )
    mongo_client.server_info()
    db                = mongo_client["sensix_panel"]
    subadmins_col     = db["subadmins"]
    fetchers_col      = db["fetchers"]
    uid_ownership_col = db["uid_ownership"]
    credit_log_col    = db["credit_log"]
    print("MongoDB connected OK")
except Exception as e:
    print(f"MongoDB FAILED: {e}")
    mongo_client = db = subadmins_col = fetchers_col = uid_ownership_col = credit_log_col = None


# ===== KEEP-ALIVE SELF-PING (FIX) =====
def self_ping():
    """
    Render Free Tier ১৫ মিনিট inactivity-তে sleep করে।
    তাই ৮ মিনিট পর পর ping করা হচ্ছে।
    SELF_URL env variable অবশ্যই সেট করতে হবে।
    """
    # অ্যাপ পুরো start হওয়ার জন্য ৩০ সেকেন্ড অপেক্ষা
    time.sleep(30)
    print(f"[SELF-PING] Keep-alive started. Target: {SELF_URL or 'NOT SET — ping disabled!'}")

    while True:
        if SELF_URL:
            try:
                resp = requests.get(SELF_URL + "/ping", timeout=15)
                print(f"[SELF-PING] OK ({resp.status_code}) — {datetime.utcnow().strftime('%H:%M:%S UTC')}")
            except requests.exceptions.Timeout:
                print(f"[SELF-PING] Timeout — {datetime.utcnow().strftime('%H:%M:%S UTC')}")
            except Exception as e:
                print(f"[SELF-PING] Failed: {e}")
        else:
            print("[SELF-PING] SELF_URL not set — skipping ping. Set it in environment variables!")

        time.sleep(8 * 60)   # ৮ মিনিট (Render 15min limit-এর অনেক আগে)


ping_thread = threading.Thread(target=self_ping, daemon=True)
ping_thread.start()


@app.route('/ping')
def ping():
    """Keep-alive endpoint — UptimeRobot এবং self-ping দুটোই এটা ব্যবহার করে"""
    return jsonify({
        "status": "alive",
        "time": datetime.utcnow().isoformat(),
        "db": "connected" if mongo_client else "disconnected"
    }), 200


# ===== NEW API HELPERS =====
def api_add_uid(uid, days=1):
    url = f"{UID_API_BASE}/uid"
    params = {"add": uid, "days": days}
    try:
        r = requests.get(url, params=params, timeout=20)
        try:
            return r.json(), r.status_code
        except Exception:
            return {"message": r.text}, r.status_code
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}, 503

def api_remove_uid(uid):
    url = f"{UID_API_BASE}/remove"
    params = {"uid": uid}
    try:
        r = requests.get(url, params=params, timeout=20)
        try:
            return r.json(), r.status_code
        except Exception:
            return {"message": r.text}, r.status_code
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}, 503

def api_list_uids():
    if uid_ownership_col is None:
        return [], 200
    docs = list(uid_ownership_col.find({}, {"_id": 0}))
    return docs, 200


# ===== HELPERS =====
def merge_expiry(uids):
    if uid_ownership_col is None:
        return uids
    for u in uids:
        uid_val = u.get("uid") or u.get("id") or ""
        if not uid_val:
            continue
        doc = uid_ownership_col.find_one({"uid": uid_val})
        if doc:
            u["expires_at"] = doc.get("expires_at", "")
            if not u.get("name"):
                u["name"] = doc.get("name", "")
            if not u.get("days"):
                u["days"] = doc.get("days", "")
    return uids

def save_uid_meta(uid, name, days, owner="main_admin", extend=False):
    if uid_ownership_col is None:
        return
    if extend:
        doc = uid_ownership_col.find_one({"uid": uid})
        if doc and doc.get("expires_at"):
            try:
                old_exp = datetime.fromisoformat(doc["expires_at"])
                new_exp = max(old_exp, datetime.utcnow()) + timedelta(days=days)
            except Exception:
                new_exp = datetime.utcnow() + timedelta(days=days)
        else:
            new_exp = datetime.utcnow() + timedelta(days=days)
    else:
        new_exp = datetime.utcnow() + timedelta(days=days)

    uid_ownership_col.update_one(
        {"uid": uid},
        {"$set": {
            "uid":        uid,
            "name":       name,
            "days":       days,
            "owner":      owner,
            "expires_at": new_exp.isoformat(),
            "added_at":   datetime.utcnow().isoformat()
        }},
        upsert=True
    )

def get_subadmin_credits(username):
    if subadmins_col is None:
        return 0
    doc = subadmins_col.find_one({"username": username})
    if not doc:
        return 0
    return doc.get("credits", 0)

def deduct_credit(username):
    if subadmins_col is None:
        return False
    doc = subadmins_col.find_one({"username": username})
    if not doc:
        return False
    current = doc.get("credits", 0)
    if current < 1:
        return False
    subadmins_col.update_one({"username": username}, {"$inc": {"credits": -1}})
    if credit_log_col is not None:
        credit_log_col.insert_one({
            "username":     username,
            "change":       -1,
            "balance_after": current - 1,
            "reason":       "UID added",
            "date":         datetime.utcnow().isoformat()
        })
    return True


# ===== FETCHER HELPERS (✅ NEW — third user tier) =====
def verify_fetcher(username, password):
    """Fetcher login check — same pattern as verify_subadmin."""
    if fetchers_col is None:
        return False
    return fetchers_col.find_one({"username": username, "password": password}) is not None

def get_fetcher_permission_days(username):
    """Returns the admin-configured permission_days for a fetcher (0 if not found)."""
    if fetchers_col is None:
        return 0
    doc = fetchers_col.find_one({"username": username})
    if not doc:
        return 0
    return int(doc.get("permission_days", 0))


# ===== FRONTEND =====
@app.route('/')
def index():
    return render_template('index.html')


# ===== MAIN ADMIN AUTH =====
@app.route('/admin/verify', methods=['POST'])
def admin_verify():
    data = request.json or {}
    if data.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    return jsonify({"status": "success", "role": "main_admin"}), 200


# ===== ADMIN — LIST =====
@app.route('/admin/list', methods=['GET'])
def admin_list():
    if request.args.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    uids, code = api_list_uids()
    if code != 200:
        return jsonify({"status": "error", "message": "Failed to fetch UIDs"}), code
    uids = [u for u in uids if u.get("status", "active") != "removed"]
    return jsonify({"status": "success", "total": len(uids), "licenses": uids}), 200


# ===== ADMIN — CREATE =====
@app.route('/admin/create', methods=['POST'])
def admin_create():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    uid  = body.get("uid", "").strip()
    days = int(body.get("days", 1))
    name = body.get("name", "Player").strip()
    if not uid:
        return jsonify({"status": "error", "message": "uid required"}), 400
    data, code = api_add_uid(uid, days)
    if code in (200, 201):
        save_uid_meta(uid, name, days, owner="main_admin", extend=False)
        return jsonify({"status": "success", "message": "UID added", "data": data}), 200
    return jsonify({"status": "error", "message": data.get("message", data.get("error", "API error"))}), code


# ===== ADMIN — REVOKE =====
@app.route('/admin/revoke', methods=['POST'])
def admin_revoke():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    uid = body.get("uid", "").strip()
    if not uid:
        return jsonify({"status": "error", "message": "uid required"}), 400
    data, code = api_remove_uid(uid)
    if uid_ownership_col is not None:
        uid_ownership_col.delete_one({"uid": uid})
    if code == 200:
        return jsonify({"status": "success", "message": f"UID {uid} removed"}), 200
    return jsonify({"status": "error", "message": data.get("message", data.get("error", "API error"))}), code


# ===== ADMIN — UPDATE/RENEW =====
@app.route('/admin/update', methods=['POST'])
def admin_update():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    uid  = body.get("uid", "").strip()
    days = int(body.get("days", 1))
    if not uid:
        return jsonify({"status": "error", "message": "uid required"}), 400
    api_remove_uid(uid)
    data, code = api_add_uid(uid, days)
    if code in (200, 201):
        existing_name = "Player"
        if uid_ownership_col is not None:
            doc = uid_ownership_col.find_one({"uid": uid})
            if doc:
                existing_name = doc.get("name", "Player")
        save_uid_meta(uid, existing_name, days, extend=True)
        return jsonify({"status": "success", "message": f"UID {uid} renewed {days}d", "data": data}), 200
    return jsonify({"status": "error", "message": data.get("message", data.get("error", "API error"))}), code


# ===== SUB-ADMIN MANAGEMENT =====
@app.route('/admin/create-subadmin', methods=['POST'])
def create_subadmin():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if subadmins_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500

    username        = body.get("username", "").strip()
    password        = body.get("password", "").strip()
    note            = body.get("note", "").strip()
    initial_credits = int(body.get("credits", 0))

    if not username or not password:
        return jsonify({"status": "error", "message": "username and password required"}), 400
    if subadmins_col.find_one({"username": username}):
        return jsonify({"status": "error", "message": "Username already exists"}), 409

    subadmins_col.insert_one({
        "username":   username,
        "password":   password,
        "note":       note,
        "credits":    initial_credits,
        "created_at": datetime.utcnow()
    })

    if initial_credits > 0 and credit_log_col is not None:
        credit_log_col.insert_one({
            "username":     username,
            "change":       initial_credits,
            "balance_after": initial_credits,
            "reason":       "Initial credits on account creation",
            "date":         datetime.utcnow().isoformat()
        })

    return jsonify({"status": "success", "message": f"Sub-admin '{username}' created", "credits": initial_credits}), 200


# ===== GIVE CREDITS =====
@app.route('/admin/give-credits', methods=['POST'])
def give_credits():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if subadmins_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500

    username = body.get("username", "").strip()
    amount   = int(body.get("amount", 0))

    if not username:
        return jsonify({"status": "error", "message": "username required"}), 400
    if amount < 1:
        return jsonify({"status": "error", "message": "amount must be at least 1"}), 400

    doc = subadmins_col.find_one({"username": username})
    if not doc:
        return jsonify({"status": "error", "message": f"Reseller '{username}' not found"}), 404

    subadmins_col.update_one({"username": username}, {"$inc": {"credits": amount}})
    new_balance = doc.get("credits", 0) + amount

    if credit_log_col is not None:
        credit_log_col.insert_one({
            "username":     username,
            "change":       amount,
            "balance_after": new_balance,
            "reason":       "Admin top-up",
            "date":         datetime.utcnow().isoformat()
        })

    return jsonify({"status": "success", "message": f"Added {amount} credits to {username}", "new_credits": new_balance}), 200


# ===== CREDIT LOG =====
@app.route('/admin/credit-log', methods=['GET'])
def get_credit_log():
    if request.args.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if credit_log_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500
    logs = list(credit_log_col.find({}, {"_id": 0}).sort("date", -1).limit(200))
    return jsonify({"status": "success", "logs": logs}), 200


# ===== LIST SUBADMINS =====
@app.route('/admin/list-subadmins', methods=['GET'])
def list_subadmins():
    if request.args.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if subadmins_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500
    result = [
        {"username": sa["username"], "note": sa.get("note", ""), "credits": sa.get("credits", 0), "active": True}
        for sa in subadmins_col.find({}, {"_id": 0, "password": 0})
    ]
    return jsonify({"status": "success", "subadmins": result}), 200


@app.route('/admin/delete-subadmin', methods=['POST'])
def delete_subadmin():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if subadmins_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500
    username = body.get("username", "").strip()
    result   = subadmins_col.delete_one({"username": username})
    if result.deleted_count == 0:
        return jsonify({"status": "error", "message": "Sub-admin not found"}), 404
    return jsonify({"status": "success", "message": f"Sub-admin '{username}' deleted"}), 200


# ===== ✅ NEW: FETCHER MANAGEMENT (Main Admin side) =====
# A Fetcher is a third user tier: Admin creates them with a username/password
# AND a permission_days value. Every UID that fetcher ever adds/renews is
# forced to last exactly permission_days — the fetcher never chooses the days.

@app.route('/admin/create-fetcher', methods=['POST'])
def create_fetcher():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if fetchers_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500

    username        = body.get("username", "").strip()
    password        = body.get("password", "").strip()
    note            = body.get("note", "").strip()
    permission_days = int(body.get("permission_days", 30))

    if not username or not password:
        return jsonify({"status": "error", "message": "username and password required"}), 400
    if permission_days < 1:
        return jsonify({"status": "error", "message": "permission_days must be at least 1"}), 400
    if fetchers_col.find_one({"username": username}):
        return jsonify({"status": "error", "message": "Username already exists"}), 409

    fetchers_col.insert_one({
        "username":        username,
        "password":        password,
        "note":            note,
        "permission_days": permission_days,
        "created_at":      datetime.utcnow()
    })

    return jsonify({
        "status": "success",
        "message": f"Fetcher '{username}' created",
        "permission_days": permission_days
    }), 200


@app.route('/admin/list-fetchers', methods=['GET'])
def list_fetchers():
    if request.args.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if fetchers_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500
    result = [
        {
            "username": f["username"],
            "note": f.get("note", ""),
            "permission_days": f.get("permission_days", 0)
        }
        for f in fetchers_col.find({}, {"_id": 0, "password": 0})
    ]
    return jsonify({"status": "success", "fetchers": result}), 200


@app.route('/admin/update-fetcher-permission', methods=['POST'])
def update_fetcher_permission():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if fetchers_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500

    username        = body.get("username", "").strip()
    permission_days = int(body.get("permission_days", 0))

    if not username:
        return jsonify({"status": "error", "message": "username required"}), 400
    if permission_days < 1:
        return jsonify({"status": "error", "message": "permission_days must be at least 1"}), 400

    result = fetchers_col.update_one(
        {"username": username},
        {"$set": {"permission_days": permission_days}}
    )
    if result.matched_count == 0:
        return jsonify({"status": "error", "message": f"Fetcher '{username}' not found"}), 404

    return jsonify({
        "status": "success",
        "message": f"'{username}' permission set to {permission_days} days",
        "permission_days": permission_days
    }), 200


@app.route('/admin/delete-fetcher', methods=['POST'])
def delete_fetcher():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if fetchers_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500
    username = body.get("username", "").strip()
    result   = fetchers_col.delete_one({"username": username})
    if result.deleted_count == 0:
        return jsonify({"status": "error", "message": "Fetcher not found"}), 404
    return jsonify({"status": "success", "message": f"Fetcher '{username}' deleted"}), 200


# ===== SUB-ADMIN AUTH =====
def verify_subadmin(username, password):
    if subadmins_col is None:
        return False
    return subadmins_col.find_one({"username": username, "password": password}) is not None

@app.route('/subadmin/login', methods=['POST'])
def subadmin_login():
    body = request.json or {}
    if verify_subadmin(body.get("username", ""), body.get("password", "")):
        return jsonify({"status": "success", "role": "sub_admin", "username": body["username"]}), 200
    return jsonify({"status": "error", "message": "Invalid credentials"}), 403


# ===== SUB-ADMIN CREDITS =====
@app.route('/subadmin/credits', methods=['GET'])
def subadmin_credits():
    username = request.args.get("username", "")
    password = request.args.get("password", "")
    if not verify_subadmin(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    credits = get_subadmin_credits(username)
    return jsonify({"status": "success", "credits": credits, "username": username}), 200


# ===== SUB-ADMIN — LIST =====
@app.route('/subadmin/list', methods=['GET'])
def subadmin_list():
    username = request.args.get("username", "")
    password = request.args.get("password", "")
    if not verify_subadmin(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    all_uids, code = api_list_uids()
    if code != 200:
        return jsonify({"status": "error", "message": "Failed to fetch UIDs"}), code

    all_uids = [u for u in all_uids if u.get("status", "active") != "removed"]

    if uid_ownership_col is not None:
        owned   = set(doc["uid"] for doc in uid_ownership_col.find({"owner": username}, {"uid": 1}))
        my_uids = [u for u in all_uids if (u.get("uid") or u.get("id") or "") in owned]
    else:
        my_uids = all_uids

    return jsonify({"status": "success", "total": len(my_uids), "licenses": my_uids}), 200


# ===== SUB-ADMIN — CREATE =====
@app.route('/subadmin/create', methods=['POST'])
def subadmin_create():
    body     = request.json or {}
    username = body.get("username", "")
    password = body.get("password", "")
    if not verify_subadmin(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    current_credits = get_subadmin_credits(username)
    if current_credits < 1:
        return jsonify({"status": "error", "message": "❌ No credits! Contact Main Admin."}), 402

    uid  = body.get("uid", "").strip()
    days = int(body.get("days", 1))
    name = body.get("name", "Player").strip()
    if not uid:
        return jsonify({"status": "error", "message": "uid required"}), 400

    data, code = api_add_uid(uid, days)
    if code in (200, 201):
        deduct_credit(username)
        save_uid_meta(uid, name, days, owner=username, extend=False)
        new_credits = get_subadmin_credits(username)
        return jsonify({"status": "success", "message": "UID added", "credits_remaining": new_credits, "data": data}), 200

    return jsonify({"status": "error", "message": data.get("message", data.get("error", "API error"))}), code


# ===== SUB-ADMIN — REVOKE =====
@app.route('/subadmin/revoke', methods=['POST'])
def subadmin_revoke():
    body     = request.json or {}
    username = body.get("username", "")
    password = body.get("password", "")
    if not verify_subadmin(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    uid = body.get("uid", "").strip()
    if not uid:
        return jsonify({"status": "error", "message": "uid required"}), 400

    if uid_ownership_col is not None:
        ownership = uid_ownership_col.find_one({"uid": uid})
        if ownership and ownership.get("owner") != username:
            return jsonify({"status": "error", "message": "You can only remove UIDs you added"}), 403

    data, code = api_remove_uid(uid)
    if uid_ownership_col is not None:
        uid_ownership_col.delete_one({"uid": uid})
    if code == 200:
        return jsonify({"status": "success", "message": f"UID {uid} removed"}), 200
    return jsonify({"status": "error", "message": data.get("message", data.get("error", "API error"))}), code


# ===== SUB-ADMIN — UPDATE/RENEW =====
@app.route('/subadmin/update', methods=['POST'])
def subadmin_update():
    body     = request.json or {}
    username = body.get("username", "")
    password = body.get("password", "")
    if not verify_subadmin(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    uid  = body.get("uid", "").strip()
    days = int(body.get("days", 1))
    if not uid:
        return jsonify({"status": "error", "message": "uid required"}), 400

    api_remove_uid(uid)
    data, code = api_add_uid(uid, days)
    if code in (200, 201):
        existing_name = "Player"
        if uid_ownership_col is not None:
            doc = uid_ownership_col.find_one({"uid": uid})
            if doc:
                existing_name = doc.get("name", "Player")
        save_uid_meta(uid, existing_name, days, owner=username, extend=True)
        return jsonify({"status": "success", "message": f"UID {uid} renewed {days}d", "data": data}), 200
    return jsonify({"status": "error", "message": data.get("message", data.get("error", "API error"))}), code


# ===== ✅ NEW: FETCHER AUTH & ACTIONS (Fetcher side — third user tier) =====
# Fetchers never send a "days" value from the frontend for create/update — the
# server always looks up their own permission_days and uses that, so a fetcher
# can never grant themselves more or less time than the Admin configured.

@app.route('/fetcher/login', methods=['POST'])
def fetcher_login():
    body = request.json or {}
    if verify_fetcher(body.get("username", ""), body.get("password", "")):
        return jsonify({"status": "success", "role": "fetcher", "username": body["username"]}), 200
    return jsonify({"status": "error", "message": "Invalid credentials"}), 403


# ===== ✅ UNIFIED LOGIN (auto-detects main_admin / sub_admin / fetcher) =====
@app.route('/unified/login', methods=['POST'])
def unified_login():
    """
    Frontend single login box সব role-এর জন্য এই একটাই endpoint কল করে।
    identifier = admin_key OR username, password = password (admin_key হলে ফাঁকা থাকতে পারে)
    """
    body = request.json or {}
    identifier = (body.get("identifier") or "").strip()
    password   = (body.get("password") or "").strip()

    if not identifier and not password:
        return jsonify({"status": "error", "message": "Identifier or password required"}), 400

    # 1) Main Admin — identifier is treated as the master admin key
    #    (works whether the key was typed into the identifier box or password box)
    if identifier == ADMIN_KEY or password == ADMIN_KEY:
        return jsonify({"status": "success", "role": "main_admin", "admin_key": ADMIN_KEY}), 200

    # 2) Sub-Admin (Reseller)
    if verify_subadmin(identifier, password):
        return jsonify({"status": "success", "role": "sub_admin", "username": identifier}), 200

    # 3) Fetcher (Trail)
    if verify_fetcher(identifier, password):
        return jsonify({"status": "success", "role": "fetcher", "username": identifier}), 200

    return jsonify({"status": "error", "message": "Invalid username, password, or Master Key"}), 403


@app.route('/fetcher/permission', methods=['GET'])
def fetcher_permission():
    username = request.args.get("username", "")
    password = request.args.get("password", "")
    if not verify_fetcher(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    days = get_fetcher_permission_days(username)
    return jsonify({"status": "success", "permission_days": days, "username": username}), 200


@app.route('/fetcher/list', methods=['GET'])
def fetcher_list():
    username = request.args.get("username", "")
    password = request.args.get("password", "")
    if not verify_fetcher(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    all_uids, code = api_list_uids()
    if code != 200:
        return jsonify({"status": "error", "message": "Failed to fetch UIDs"}), code

    all_uids = [u for u in all_uids if u.get("status", "active") != "removed"]

    if uid_ownership_col is not None:
        owned   = set(doc["uid"] for doc in uid_ownership_col.find({"owner": username}, {"uid": 1}))
        my_uids = [u for u in all_uids if (u.get("uid") or u.get("id") or "") in owned]
    else:
        my_uids = all_uids

    return jsonify({"status": "success", "total": len(my_uids), "licenses": my_uids}), 200


@app.route('/fetcher/create', methods=['POST'])
def fetcher_create():
    body     = request.json or {}
    username = body.get("username", "")
    password = body.get("password", "")
    if not verify_fetcher(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    permission_days = get_fetcher_permission_days(username)
    if permission_days < 1:
        return jsonify({"status": "error", "message": "❌ No permission set! Contact Main Admin."}), 402

    uid  = body.get("uid", "").strip()
    name = body.get("name", "Player").strip()
    if not uid:
        return jsonify({"status": "error", "message": "uid required"}), 400

    # Ignore any "days" the client might send — always use the server-side permission.
    data, code = api_add_uid(uid, permission_days)
    if code in (200, 201):
        save_uid_meta(uid, name, permission_days, owner=username, extend=False)
        return jsonify({"status": "success", "message": f"UID added ({permission_days}d)", "data": data}), 200

    return jsonify({"status": "error", "message": data.get("message", data.get("error", "API error"))}), code


@app.route('/fetcher/revoke', methods=['POST'])
def fetcher_revoke():
    body     = request.json or {}
    username = body.get("username", "")
    password = body.get("password", "")
    if not verify_fetcher(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    uid = body.get("uid", "").strip()
    if not uid:
        return jsonify({"status": "error", "message": "uid required"}), 400

    if uid_ownership_col is not None:
        ownership = uid_ownership_col.find_one({"uid": uid})
        if ownership and ownership.get("owner") != username:
            return jsonify({"status": "error", "message": "You can only remove UIDs you added"}), 403

    data, code = api_remove_uid(uid)
    if uid_ownership_col is not None:
        uid_ownership_col.delete_one({"uid": uid})
    if code == 200:
        return jsonify({"status": "success", "message": f"UID {uid} removed"}), 200
    return jsonify({"status": "error", "message": data.get("message", data.get("error", "API error"))}), code


@app.route('/fetcher/update', methods=['POST'])
def fetcher_update():
    body     = request.json or {}
    username = body.get("username", "")
    password = body.get("password", "")
    if not verify_fetcher(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    permission_days = get_fetcher_permission_days(username)
    if permission_days < 1:
        return jsonify({"status": "error", "message": "❌ No permission set! Contact Main Admin."}), 402

    uid = body.get("uid", "").strip()
    if not uid:
        return jsonify({"status": "error", "message": "uid required"}), 400

    if uid_ownership_col is not None:
        ownership = uid_ownership_col.find_one({"uid": uid})
        if ownership and ownership.get("owner") != username:
            return jsonify({"status": "error", "message": "You can only renew UIDs you added"}), 403

    # Ignore any "days" the client might send — always renew by the server-side permission.
    api_remove_uid(uid)
    data, code = api_add_uid(uid, permission_days)
    if code in (200, 201):
        existing_name = "Player"
        if uid_ownership_col is not None:
            doc = uid_ownership_col.find_one({"uid": uid})
            if doc:
                existing_name = doc.get("name", "Player")
        save_uid_meta(uid, existing_name, permission_days, owner=username, extend=True)
        return jsonify({"status": "success", "message": f"UID {uid} renewed {permission_days}d", "data": data}), 200
    return jsonify({"status": "error", "message": data.get("message", data.get("error", "API error"))}), code


# ===== ADMIN — CHANGE KEY =====
@app.route('/admin/change-key', methods=['POST'])
def admin_change_key():
    global ADMIN_KEY
    body = request.json or {}
    old_key = body.get("admin_key", "").strip()
    new_key = body.get("new_key", "").strip()
    if not old_key or not new_key:
        return jsonify({"status": "error", "message": "Both current key and new key are required"}), 400
    if old_key != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Current admin key is incorrect"}), 403
    if len(new_key) < 6:
        return jsonify({"status": "error", "message": "New key must be at least 6 characters"}), 400
    ADMIN_KEY = new_key
    return jsonify({"status": "success", "message": "Master admin key updated successfully"}), 200


# ===== DB STATUS =====
@app.route('/admin/db-status', methods=['GET'])
def db_status():
    if request.args.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if subadmins_col is None:
        return jsonify({"status": "error", "message": "MongoDB NOT connected"}), 500
    return jsonify({"status": "success", "message": "MongoDB connected OK"}), 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8002))
    app.run(host='0.0.0.0', port=port, debug=False)
