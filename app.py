import json
import os
import requests
import threading
import time
# pyrefly: ignore [missing-import]
from flask import Flask, request, jsonify, render_template
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from pymongo import MongoClient, ReturnDocument
from datetime import datetime, timedelta

load_dotenv()

app = Flask(__name__)

# CONFIG
UID_API_BASE       = os.environ.get("UID_API_BASE", "https://uid.syntaxcorporation.online")
AUTHCLOUD_API_BASE = os.environ.get("AUTHCLOUD_API_BASE", "http://194.233.76.156:10077/lib/api").rstrip("/")
ADMIN_KEY          = os.environ.get("ADMIN_KEY",    "changeme_admin_key")
SELF_URL           = os.environ.get("SELF_URL",     "").rstrip("/")   # ← trailing slash সরানো হয়েছে

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
    db                    = mongo_client["sensix_panel"]
    subadmins_col         = db["subadmins"]
    fetchers_col          = db["fetchers"]
    uid_ownership_col     = db["uid_ownership"]
    credit_log_col        = db["credit_log"]
    trail_users_col       = db["trail_users"]
    trail_keys_col        = db["trail_keys"]
    key_resellers_col     = db["key_resellers"]
    license_keys_log_col  = db["license_keys_log"]
    print("MongoDB connected OK")
except Exception as e:
    print(f"MongoDB FAILED: {e}")
    mongo_client = db = subadmins_col = fetchers_col = uid_ownership_col = credit_log_col = trail_users_col = trail_keys_col = key_resellers_col = license_keys_log_col = None


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


def get_client_ip():
    """Extracts client IP address respecting reverse proxies (Render, Cloudflare, Nginx)"""
    if request.headers.get("CF-Connecting-IP"):
        return request.headers.get("CF-Connecting-IP").split(",")[0].strip()
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    if request.headers.get("X-Real-IP"):
        return request.headers.get("X-Real-IP").split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


def verify_trail_user(username, password):
    """Trail user login check."""
    if trail_users_col is None:
        return False
    return trail_users_col.find_one({"username": username, "password": password}) is not None


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


# ===== ✅ FREE BYPASS TRAIL MANAGEMENT (Admin & User) =====

@app.route('/admin/create-trail-user', methods=['POST'])
def create_trail_user():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if trail_users_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500

    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    note     = body.get("note", "").strip()

    if not username or not password:
        return jsonify({"status": "error", "message": "Username and password are required"}), 400

    if trail_users_col.find_one({"username": username}):
        return jsonify({"status": "error", "message": "Trail username already exists"}), 409

    trail_users_col.insert_one({
        "username":    username,
        "password":    password,
        "note":        note,
        "claimed_key": None,
        "claimed_at":  None,
        "created_at":  datetime.utcnow().isoformat()
    })

    return jsonify({
        "status": "success",
        "message": f"Trail user '{username}' created successfully"
    }), 200


@app.route('/admin/list-trail-users', methods=['GET'])
def list_trail_users():
    if request.args.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if trail_users_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500

    users = list(trail_users_col.find({}, {"_id": 0, "password": 0}))
    if trail_keys_col is not None:
        for u in users:
            uname = u.get("username")
            u["claimed_count"] = trail_keys_col.count_documents({"claimed_by": uname, "status": "claimed"})
    return jsonify({
        "status": "success",
        "total": len(users),
        "users": users
    }), 200


@app.route('/admin/delete-trail-user', methods=['POST'])
def delete_trail_user():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if trail_users_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500

    username = body.get("username", "").strip()
    user = trail_users_col.find_one({"username": username})
    if not user:
        return jsonify({"status": "error", "message": "Trail user not found"}), 404

    # Release any keys claimed by this username back to pool
    if trail_keys_col is not None:
        trail_keys_col.update_many(
            {"claimed_by": username},
            {"$set": {"status": "available", "claimed_by": None, "claimed_ip": None, "claimed_at": None}}
        )

    trail_users_col.delete_one({"username": username})
    return jsonify({"status": "success", "message": f"Trail user '{username}' deleted (associated keys returned to pool)"}), 200


@app.route('/admin/add-trail-keys', methods=['POST'])
def add_trail_keys():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if trail_keys_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500

    raw_keys = body.get("keys", "")
    if isinstance(raw_keys, str):
        import re
        tokens = re.split(r'[\r\n,;]+', raw_keys)
    elif isinstance(raw_keys, list):
        tokens = raw_keys
    else:
        tokens = []

    keys_to_add = [t.strip() for t in tokens if t and t.strip()]
    if not keys_to_add:
        return jsonify({"status": "error", "message": "Please provide at least one key"}), 400

    added_count = 0
    duplicate_count = 0
    now_iso = datetime.utcnow().isoformat()

    for k in keys_to_add:
        existing = trail_keys_col.find_one({"key": k})
        if existing:
            duplicate_count += 1
        else:
            trail_keys_col.insert_one({
                "key": k,
                "status": "available",
                "claimed_by": None,
                "claimed_ip": None,
                "claimed_at": None,
                "added_at": now_iso
            })
            added_count += 1

    return jsonify({
        "status": "success",
        "message": f"Added {added_count} new key(s) ({duplicate_count} duplicates skipped)",
        "added_count": added_count,
        "duplicate_count": duplicate_count
    }), 200


@app.route('/admin/list-trail-keys', methods=['GET'])
def list_trail_keys():
    if request.args.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if trail_keys_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500

    keys = list(trail_keys_col.find({}, {"_id": 0}).sort("added_at", -1))
    total_keys = len(keys)
    available_keys = sum(1 for k in keys if k.get("status") == "available")
    claimed_keys = total_keys - available_keys

    return jsonify({
        "status": "success",
        "total": total_keys,
        "available": available_keys,
        "claimed": claimed_keys,
        "keys": keys
    }), 200


@app.route('/admin/delete-trail-key', methods=['POST'])
def delete_trail_key():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if trail_keys_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500

    key = body.get("key", "").strip()
    if not key:
        return jsonify({"status": "error", "message": "Key is required"}), 400

    result = trail_keys_col.delete_one({"key": key})
    if result.deleted_count == 0:
        return jsonify({"status": "error", "message": "Key not found"}), 404

    if trail_users_col is not None:
        trail_users_col.update_many({"claimed_key": key}, {"$set": {"claimed_key": None, "claimed_at": None}})
        trail_users_col.update_many({"claimed_keys": key}, {"$pull": {"claimed_keys": key}})

    return jsonify({"status": "success", "message": "Key deleted from pool"}), 200


@app.route('/admin/reset-trail-key', methods=['POST'])
def reset_trail_key():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if trail_keys_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500

    key = body.get("key", "").strip()
    if not key:
        return jsonify({"status": "error", "message": "Key is required"}), 400

    result = trail_keys_col.update_one(
        {"key": key},
        {"$set": {
            "status": "available",
            "claimed_by": None,
            "claimed_ip": None,
            "claimed_at": None
        }}
    )
    if result.matched_count == 0:
        return jsonify({"status": "error", "message": "Key not found"}), 404

    if trail_users_col is not None:
        trail_users_col.update_many({"claimed_key": key}, {"$set": {"claimed_key": None, "claimed_at": None}})
        trail_users_col.update_many({"claimed_keys": key}, {"$pull": {"claimed_keys": key}})

    return jsonify({"status": "success", "message": f"Key '{key}' reset to available pool"}), 200


# ===== TRAIL USER ENDPOINTS =====

@app.route('/trail/login', methods=['POST'])
def trail_login():
    body = request.json or {}
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    if not verify_trail_user(username, password):
        return jsonify({"status": "error", "message": "Invalid username or password"}), 403

    user = trail_users_col.find_one({"username": username}, {"_id": 0, "password": 0})
    return jsonify({
        "status": "success",
        "role": "trail",
        "username": username,
        "user": user
    }), 200


@app.route('/trail/status', methods=['GET'])
def trail_status():
    username = request.args.get("username", "").strip()
    password = request.args.get("password", "").strip()
    if not verify_trail_user(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    client_ip = get_client_ip()

    available_stock = 0
    if trail_keys_col is not None:
        available_stock = trail_keys_col.count_documents({"status": "available"})

    # Check if this IP address has already claimed a key
    claimed_doc = None
    if trail_keys_col is not None:
        claimed_doc = trail_keys_col.find_one({
            "claimed_ip": client_ip,
            "status": "claimed"
        })

    has_key = bool(claimed_doc and claimed_doc.get("key"))

    return jsonify({
        "status": "success",
        "username": username,
        "client_ip": client_ip,
        "claimed_key": claimed_doc.get("key") if has_key else None,
        "claimed_at": claimed_doc.get("claimed_at") if has_key else None,
        "has_key": has_key,
        "available_stock": available_stock
    }), 200


@app.route('/trail/claim-key', methods=['POST'])
def trail_claim_key():
    body = request.json or {}
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    if not verify_trail_user(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    if trail_users_col is None or trail_keys_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500

    user = trail_users_col.find_one({"username": username})
    if not user:
        return jsonify({"status": "error", "message": "User not found"}), 404

    client_ip = get_client_ip()

    # Rule: 1 IP = 1 Key limit!
    # A key claimed from an IP can never be claimed again, and that IP cannot claim another key.
    existing_ip_claim = trail_keys_col.find_one({
        "claimed_ip": client_ip,
        "status": "claimed"
    })
    if existing_ip_claim:
        return jsonify({
            "status": "already_claimed",
            "message": "This IP address has already claimed 1 Free Bypass Key!",
            "key": existing_ip_claim["key"],
            "claimed_at": existing_ip_claim.get("claimed_at"),
            "client_ip": client_ip
        }), 200

    now_iso = datetime.utcnow().isoformat()
    # Atomically pick an unclaimed key from the available pool
    claimed_doc = trail_keys_col.find_one_and_update(
        {"status": "available"},
        {"$set": {
            "status": "claimed",
            "claimed_by": username,
            "claimed_ip": client_ip,
            "claimed_at": now_iso
        }},
        return_document=ReturnDocument.AFTER
    )

    if not claimed_doc:
        return jsonify({
            "status": "error",
            "message": "No keys available in stock right now! Please contact Admin."
        }), 404

    assigned_key = claimed_doc["key"]

    trail_users_col.update_one(
        {"username": username},
        {
            "$set": {
                "latest_claimed_key": assigned_key,
                "latest_claimed_at": now_iso
            },
            "$addToSet": {
                "claimed_ips": client_ip,
                "claimed_keys": assigned_key
            }
        }
    )

    return jsonify({
        "status": "success",
        "message": "Free Bypass Key claimed successfully! (1 Key per IP limit)",
        "key": assigned_key,
        "claimed_at": now_iso,
        "client_ip": client_ip
    }), 200


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

    # 2) Key Reseller or Sub-Admin (Reseller)
    key_res = find_key_reseller(identifier)
    if key_res and key_res.get("password") == password:
        lim = int(key_res.get("key_limit", 0))
        usd = int(key_res.get("keys_used", 0))
        return jsonify({
            "status": "success",
            "role": "key_reseller",
            "username": identifier,
            "key_limit": lim,
            "keys_used": usd,
            "remaining": max(0, lim - usd)
        }), 200

    if verify_subadmin(identifier, password):
        return jsonify({"status": "success", "role": "sub_admin", "username": identifier}), 200

    # 3) Free Bypass Trail User
    if verify_trail_user(identifier, password):
        return jsonify({"status": "success", "role": "trail", "username": identifier}), 200

    # 4) Fetcher (Legacy / Fallback)
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


# ==============================================================================
# ===== AUTHCLOUD LICENSE KEYS & RESELLER QUOTA SYSTEM ========================
# ==============================================================================

RESELLER_LOCAL_FILE = os.path.join(os.path.dirname(__file__), "resellers_quota.json")

def get_all_key_resellers():
    """Retrieve all key resellers from Mongo or local fallback"""
    if key_resellers_col is not None:
        try:
            return list(key_resellers_col.find({}, {"_id": 0}))
        except Exception as e:
            print(f"[RESELLER DB ERR] {e}")
    if os.path.exists(RESELLER_LOCAL_FILE):
        try:
            with open(RESELLER_LOCAL_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def find_key_reseller(username):
    """Find a specific reseller by username"""
    if key_resellers_col is not None:
        try:
            doc = key_resellers_col.find_one({"username": username}, {"_id": 0})
            if doc:
                return doc
        except Exception as e:
            print(f"[RESELLER FIND ERR] {e}")
    resellers = get_all_key_resellers()
    for r in resellers:
        if r.get("username") == username:
            return r
    return None

def save_key_reseller_doc(reseller_doc):
    """Save or update reseller record in Mongo and local backup"""
    username = reseller_doc.get("username")
    if key_resellers_col is not None:
        try:
            key_resellers_col.update_one(
                {"username": username},
                {"$set": reseller_doc},
                upsert=True
            )
        except Exception as e:
            print(f"[RESELLER SAVE ERR] {e}")
    # Also sync local file for zero-downtime reliability
    try:
        items = []
        if os.path.exists(RESELLER_LOCAL_FILE):
            try:
                with open(RESELLER_LOCAL_FILE, "r", encoding="utf-8") as f:
                    items = json.load(f)
            except Exception:
                items = []
        items = [i for i in items if i.get("username") != username]
        items.append(reseller_doc)
        with open(RESELLER_LOCAL_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2)
    except Exception as e:
        print(f"[RESELLER LOCAL WRITE ERR] {e}")

def delete_key_reseller_doc(username):
    """Delete reseller by username"""
    if key_resellers_col is not None:
        try:
            key_resellers_col.delete_one({"username": username})
        except Exception as e:
            print(f"[RESELLER DEL ERR] {e}")
    if os.path.exists(RESELLER_LOCAL_FILE):
        try:
            with open(RESELLER_LOCAL_FILE, "r", encoding="utf-8") as f:
                items = json.load(f)
            items = [i for i in items if i.get("username") != username]
            with open(RESELLER_LOCAL_FILE, "w", encoding="utf-8") as f:
                json.dump(items, f, indent=2)
        except Exception:
            pass


# 0. API Health & Status
@app.route('/api/authcloud/status', methods=['GET'])
def authcloud_status():
    try:
        url = f"{AUTHCLOUD_API_BASE}/status"
        resp = requests.get(url, timeout=10)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"success": True, "status": "online", "message": "AuthCloud Proxy Connected", "error": str(e)}), 200


# 1. License Directory & List
@app.route('/api/authcloud/licenses', methods=['GET'])
def authcloud_get_licenses():
    status = request.args.get("status")
    search = request.args.get("search")
    params = {}
    if status:
        params["status"] = status
    if search:
        params["search"] = search
    try:
        url = f"{AUTHCLOUD_API_BASE}/licenses"
        resp = requests.get(url, params=params, timeout=12)
        data = resp.json()
        return jsonify(data), resp.status_code
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "message": "Failed to connect to AuthCloud API"}), 502


# 2. Get Single License
@app.route('/api/authcloud/licenses/<path:key_or_id>', methods=['GET'])
def authcloud_get_single_license(key_or_id):
    try:
        url = f"{AUTHCLOUD_API_BASE}/licenses/{key_or_id}"
        resp = requests.get(url, timeout=10)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 502


# 3. Create License Key(s) with Strict Reseller Quota Enforcement
@app.route('/api/authcloud/licenses/create', methods=['POST'])
def authcloud_create_licenses():
    body = request.json or {}
    admin_key = body.get("admin_key", "").strip()
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()

    duration = body.get("duration", "30 Days").strip()
    note = body.get("note", "Dashboard Order").strip()
    try:
        count = int(body.get("count", 1))
    except (ValueError, TypeError):
        count = 1
    custom_key = body.get("key", "").strip() or None

    is_admin = (admin_key == ADMIN_KEY)
    reseller_doc = None

    if not is_admin:
        # Must be authenticated reseller
        if not username or not password:
            return jsonify({"success": False, "status": "error", "message": "Authentication required (Admin key or Reseller credentials)"}), 401
        
        reseller_doc = find_key_reseller(username)
        # Also check existing subadmin collections
        if not reseller_doc and subadmins_col is not None:
            sub = subadmins_col.find_one({"username": username, "password": password})
            if sub:
                reseller_doc = {
                    "username": username,
                    "password": password,
                    "note": sub.get("note", "Subadmin Reseller"),
                    "key_limit": sub.get("key_limit", sub.get("credits", 20)),
                    "keys_used": sub.get("keys_used", 0),
                    "created_at": sub.get("created_at", datetime.utcnow()).isoformat() if hasattr(sub.get("created_at"), "isoformat") else str(sub.get("created_at"))
                }
                save_key_reseller_doc(reseller_doc)

        if not reseller_doc or reseller_doc.get("password") != password:
            return jsonify({"success": False, "status": "error", "message": "Invalid reseller credentials"}), 403

        # Quota Verification: check remaining limit
        key_limit = int(reseller_doc.get("key_limit", 0))
        keys_used = int(reseller_doc.get("keys_used", 0))
        remaining = key_limit - keys_used

        if remaining <= 0:
            return jsonify({
                "success": False,
                "status": "limit_reached",
                "message": f"❌ Reseller key limit reached! (Quota: {key_limit}, Used: {keys_used}). Contact Admin to increase your limit.",
                "key_limit": key_limit,
                "keys_used": keys_used,
                "remaining": 0
            }), 403

        if count > remaining:
            return jsonify({
                "success": False,
                "status": "insufficient_quota",
                "message": f"❌ Cannot create {count} keys. You only have {remaining} key(s) remaining in your limit. (Quota: {key_limit}, Used: {keys_used}).",
                "key_limit": key_limit,
                "keys_used": keys_used,
                "remaining": remaining
            }), 400

    # Prepare AuthCloud API payload
    creator_tag = f"Reseller: {username}" if reseller_doc else "Master Admin"
    full_note = f"{note} [{creator_tag}]" if note else creator_tag
    payload = {
        "duration": duration,
        "note": full_note,
        "count": count
    }
    if custom_key:
        payload["key"] = custom_key

    try:
        url = f"{AUTHCLOUD_API_BASE}/licenses/create"
        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=20)
        data = resp.json()

        if resp.status_code in (200, 201) and data.get("success"):
            created_list = data.get("licenses", [])
            actual_count = len(created_list) if created_list else count

            # If reseller, update used counter and log keys
            if reseller_doc:
                new_used = int(reseller_doc.get("keys_used", 0)) + actual_count
                reseller_doc["keys_used"] = new_used
                save_key_reseller_doc(reseller_doc)

                # Log to mongo or local
                if license_keys_log_col is not None:
                    try:
                        license_keys_log_col.insert_one({
                            "reseller": username,
                            "count": actual_count,
                            "duration": duration,
                            "keys": [k.get("key") for k in created_list if isinstance(k, dict)],
                            "created_at": datetime.utcnow().isoformat()
                        })
                    except Exception as e:
                        print(f"[KEY LOG ERR] {e}")

                data["reseller_quota"] = {
                    "key_limit": int(reseller_doc.get("key_limit", 0)),
                    "keys_used": new_used,
                    "remaining": max(0, int(reseller_doc.get("key_limit", 0)) - new_used)
                }

            return jsonify(data), 200
        else:
            return jsonify(data), resp.status_code
    except Exception as e:
        return jsonify({"success": False, "status": "error", "message": f"AuthCloud API request failed: {str(e)}"}), 502


# 4. Reset HWID Binding
@app.route('/api/authcloud/licenses/reset-hwid', methods=['POST'])
def authcloud_reset_hwid():
    body = request.json or {}
    key = body.get("key", "").strip()
    if not key:
        return jsonify({"success": False, "message": "Key is required to reset HWID"}), 400
    try:
        url = f"{AUTHCLOUD_API_BASE}/licenses/reset-hwid"
        resp = requests.post(url, json={"key": key}, headers={"Content-Type": "application/json"}, timeout=15)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed to reset HWID: {str(e)}"}), 502


# 5. Ban License Key
@app.route('/api/authcloud/licenses/ban', methods=['POST'])
def authcloud_ban_license():
    body = request.json or {}
    key = body.get("key", "").strip()
    reason = body.get("reason", "Administrative action").strip()
    if not key:
        return jsonify({"success": False, "message": "Key is required to ban"}), 400
    try:
        url = f"{AUTHCLOUD_API_BASE}/licenses/ban"
        resp = requests.post(url, json={"key": key, "reason": reason}, headers={"Content-Type": "application/json"}, timeout=15)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed to ban license: {str(e)}"}), 502


# 6. Unban License Key
@app.route('/api/authcloud/licenses/unban', methods=['POST'])
def authcloud_unban_license():
    body = request.json or {}
    key = body.get("key", "").strip()
    if not key:
        return jsonify({"success": False, "message": "Key is required to unban"}), 400
    try:
        url = f"{AUTHCLOUD_API_BASE}/licenses/unban"
        resp = requests.post(url, json={"key": key}, headers={"Content-Type": "application/json"}, timeout=15)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed to unban license: {str(e)}"}), 502


# 7. Reseller Management — List All Resellers with Quota (Admin Only)
@app.route('/api/authcloud/resellers', methods=['GET'])
def authcloud_list_resellers():
    admin_key = request.args.get("admin_key", "").strip()
    if admin_key != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Unauthorized admin access"}), 403

    resellers = get_all_key_resellers()
    output = []
    for r in resellers:
        lim = int(r.get("key_limit", 0))
        usd = int(r.get("keys_used", 0))
        output.append({
            "username": r.get("username"),
            "note": r.get("note", ""),
            "key_limit": lim,
            "keys_used": usd,
            "remaining": max(0, lim - usd),
            "created_at": r.get("created_at", "")
        })
    return jsonify({"status": "success", "resellers": output, "total": len(output)}), 200


# 8. Reseller Management — Create Reseller with Limit (Admin Only)
@app.route('/api/authcloud/resellers/create', methods=['POST'])
def authcloud_create_reseller():
    body = request.json or {}
    admin_key = body.get("admin_key", "").strip()
    if admin_key != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Unauthorized admin access"}), 403

    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    note = body.get("note", "").strip()
    try:
        key_limit = int(body.get("key_limit", 20))
    except (ValueError, TypeError):
        key_limit = 20

    if not username or not password:
        return jsonify({"status": "error", "message": "Username and password required"}), 400

    existing = find_key_reseller(username)
    if existing:
        return jsonify({"status": "error", "message": f"Reseller '{username}' already exists"}), 409

    reseller_doc = {
        "username": username,
        "password": password,
        "note": note,
        "key_limit": max(0, key_limit),
        "keys_used": 0,
        "created_at": datetime.utcnow().isoformat()
    }
    save_key_reseller_doc(reseller_doc)

    return jsonify({
        "status": "success",
        "message": f"Reseller '{username}' created with key limit of {key_limit}",
        "reseller": {
            "username": username,
            "key_limit": key_limit,
            "keys_used": 0,
            "remaining": key_limit
        }
    }), 200


# 9. Reseller Management — Update Limit / Quota (Admin Only)
@app.route('/api/authcloud/resellers/update-limit', methods=['POST'])
def authcloud_update_reseller_limit():
    body = request.json or {}
    admin_key = body.get("admin_key", "").strip()
    if admin_key != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Unauthorized admin access"}), 403

    username = body.get("username", "").strip()
    if not username:
        return jsonify({"status": "error", "message": "Username required"}), 400

    reseller = find_key_reseller(username)
    if not reseller:
        return jsonify({"status": "error", "message": f"Reseller '{username}' not found"}), 404

    if "key_limit" in body:
        try:
            reseller["key_limit"] = max(0, int(body["key_limit"]))
        except (ValueError, TypeError):
            pass

    if body.get("reset_used", False):
        reseller["keys_used"] = 0

    if "note" in body:
        reseller["note"] = str(body["note"]).strip()

    if "password" in body and body["password"].strip():
        reseller["password"] = str(body["password"]).strip()

    save_key_reseller_doc(reseller)

    lim = int(reseller.get("key_limit", 0))
    usd = int(reseller.get("keys_used", 0))
    return jsonify({
        "status": "success",
        "message": f"Reseller '{username}' quota updated successfully",
        "reseller": {
            "username": username,
            "key_limit": lim,
            "keys_used": usd,
            "remaining": max(0, lim - usd)
        }
    }), 200


# 10. Reseller Management — Delete Reseller (Admin Only)
@app.route('/api/authcloud/resellers/delete', methods=['POST'])
def authcloud_delete_reseller():
    body = request.json or {}
    admin_key = body.get("admin_key", "").strip()
    if admin_key != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Unauthorized admin access"}), 403

    username = body.get("username", "").strip()
    if not username:
        return jsonify({"status": "error", "message": "Username required"}), 400

    delete_key_reseller_doc(username)
    return jsonify({"status": "success", "message": f"Reseller '{username}' removed successfully"}), 200


# 11. Reseller Profile & Quota Check
@app.route('/api/authcloud/reseller/quota', methods=['GET'])
def authcloud_reseller_quota():
    username = request.args.get("username", "").strip()
    password = request.args.get("password", "").strip()
    if not username or not password:
        return jsonify({"status": "error", "message": "Credentials required"}), 401

    reseller = find_key_reseller(username)
    if not reseller or reseller.get("password") != password:
        return jsonify({"status": "error", "message": "Invalid reseller credentials"}), 403

    lim = int(reseller.get("key_limit", 0))
    usd = int(reseller.get("keys_used", 0))
    return jsonify({
        "status": "success",
        "username": username,
        "note": reseller.get("note", ""),
        "key_limit": lim,
        "keys_used": usd,
        "remaining": max(0, lim - usd)
    }), 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8002))
    app.run(host='0.0.0.0', port=port, debug=False)

