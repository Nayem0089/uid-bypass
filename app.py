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
UID_API_BASE        = os.environ.get("UID_API_BASE", "https://uid.syntaxcorporation.online")
AUTHCLOUD_API_BASE  = os.environ.get("AUTHCLOUD_API_BASE", "https://brmodsbypass.authzen.site/api").rstrip("/")
AUTHZEN_GET_KEY_URL = os.environ.get("AUTHZEN_GET_KEY_URL", "https://brmodsbypass.authzen.site/api/get-key")
AUTHZEN_SELLER_KEY  = os.environ.get("AUTHZEN_SELLER_KEY", os.environ.get("SELLER_KEY", "RES-E961EF9C")).strip()
ADMIN_KEY           = os.environ.get("ADMIN_KEY",    "changeme_admin_key")
SELF_URL            = os.environ.get("SELF_URL",     "").rstrip("/")   # ← trailing slash সরানো হয়েছে

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
        exp = key_res.get("expiry_date", "")
        is_expired = False
        days_left = None
        if exp:
            try:
                exp_dt = datetime.strptime(exp[:10], "%Y-%m-%d")
                delta = (exp_dt - datetime.utcnow()).days
                days_left = max(0, delta)
                if delta < 0:
                    is_expired = True
            except Exception:
                pass
        return jsonify({
            "status": "success",
            "role": "key_reseller",
            "username": identifier,
            "key_limit": lim,
            "keys_used": usd,
            "remaining": max(0, lim - usd),
            "expiry_date": exp,
            "is_expired": is_expired,
            "days_left": days_left,
            "allowed_durations": key_res.get("allowed_durations", ["all"])
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

RESELLER_LOCAL_FILE     = os.path.join(os.path.dirname(__file__), "resellers_quota.json")
SELLER_KEY_LOCAL_FILE   = os.path.join(os.path.dirname(__file__), "seller_key.json")
LICENSE_KEYS_LOCAL_FILE = os.path.join(os.path.dirname(__file__), "license_keys_log.json")


def get_authzen_seller_key():
    """Get active AuthZen seller key from env, DB, or local file"""
    env_k = os.environ.get("AUTHZEN_SELLER_KEY") or os.environ.get("SELLER_KEY")
    if env_k and env_k.strip():
        return env_k.strip()
    if db is not None:
        try:
            doc = db["system_settings"].find_one({"key": "authzen_seller_key"})
            if doc and doc.get("value"):
                return doc["value"].strip()
        except Exception:
            pass
    if os.path.exists(SELLER_KEY_LOCAL_FILE):
        try:
            with open(SELLER_KEY_LOCAL_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                val = data.get("seller_key", "").strip()
                if val:
                    return val
        except Exception:
            pass
    return AUTHZEN_SELLER_KEY or "RES-E961EF9C"


def set_authzen_seller_key(seller_key):
    """Save AuthZen seller key to DB and local backup"""
    val = (seller_key or "").strip()
    if db is not None:
        try:
            db["system_settings"].update_one(
                {"key": "authzen_seller_key"},
                {"$set": {"key": "authzen_seller_key", "value": val, "updated_at": datetime.utcnow().isoformat()}},
                upsert=True
            )
        except Exception as e:
            print(f"[SETTING SAVE ERR] {e}")
    try:
        with open(SELLER_KEY_LOCAL_FILE, "w", encoding="utf-8") as f:
            json.dump({"seller_key": val, "updated_at": datetime.utcnow().isoformat()}, f, indent=2)
    except Exception as e:
        print(f"[SETTING LOCAL WRITE ERR] {e}")


def save_license_keys_local_log(log_entry):
    """Save generated license keys to local backup file"""
    try:
        logs = []
        if os.path.exists(LICENSE_KEYS_LOCAL_FILE):
            try:
                with open(LICENSE_KEYS_LOCAL_FILE, "r", encoding="utf-8") as f:
                    logs = json.load(f)
            except Exception:
                logs = []
        logs.append(log_entry)
        if len(logs) > 500:
            logs = logs[-500:]
        with open(LICENSE_KEYS_LOCAL_FILE, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=2)
    except Exception as e:
        print(f"[LOCAL KEY LOG WRITE ERR] {e}")


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
    seller_k = get_authzen_seller_key()
    return jsonify({
        "success": True,
        "status": "online",
        "api_url": AUTHZEN_GET_KEY_URL,
        "seller_key_configured": bool(seller_k),
        "message": "AuthZen API Connected (https://brmodsbypass.authzen.site/api/get-key)"
    }), 200


# 1. License Directory & List
@app.route('/api/authcloud/licenses', methods=['GET'])
def authcloud_get_licenses():
    status = request.args.get("status")
    search = request.args.get("search")

    logged_keys = []
    if license_keys_log_col is not None:
        try:
            for item in license_keys_log_col.find({}, {"_id": 0}).sort("created_at", -1).limit(200):
                keys_list = item.get("keys", [])
                for k in keys_list:
                    logged_keys.append({
                        "key": k if isinstance(k, str) else k.get("key"),
                        "duration": item.get("duration", "—"),
                        "note": item.get("note", f"Generated by {item.get('reseller', 'Admin')}"),
                        "status": "Unused",
                        "hwid": "None",
                        "created_at": item.get("created_at", "")
                    })
        except Exception as e:
            print(f"[LIC LOG DB ERR] {e}")

    if not logged_keys and os.path.exists(LICENSE_KEYS_LOCAL_FILE):
        try:
            with open(LICENSE_KEYS_LOCAL_FILE, "r", encoding="utf-8") as f:
                local_logs = json.load(f)
                for item in reversed(local_logs[-200:]):
                    for k in item.get("keys", []):
                        logged_keys.append({
                            "key": k if isinstance(k, str) else k.get("key"),
                            "duration": item.get("duration", "—"),
                            "note": item.get("note", f"Generated by {item.get('reseller', 'Admin')}"),
                            "status": "Unused",
                            "hwid": "None",
                            "created_at": item.get("created_at", "")
                        })
        except Exception:
            pass

    # Also fetch remote keys from AuthZen API (/api/key/list?seller_key=...)
    remote_keys = []
    seller_k = get_authzen_seller_key()
    try:
        keys_url = f"{AUTHCLOUD_API_BASE}/key/list?seller_key={seller_k}"
        resp = requests.get(keys_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            raw_list = data.get("keys", [])
            for k in raw_list:
                if isinstance(k, dict):
                    k_code = k.get("key_code") or k.get("key")
                    days = k.get("days", 30)
                    plan = k.get("plan", f"{days}day")
                    raw_status = (k.get("status") or "unused").strip().lower()
                    if raw_status == "banned":
                        status_str = "Banned"
                    elif raw_status == "used":
                        status_str = "Used"
                    else:
                        status_str = "Unused"
                    hwid_val = k.get("hwid_status") or "None"
                    remote_keys.append({
                        "id": k.get("id"),
                        "key": k_code,
                        "duration": f"{days} Days" if days else plan,
                        "plan": plan,
                        "note": f"AuthZen ({k.get('assigned_seller', seller_k)})",
                        "status": status_str,
                        "hwid": hwid_val,
                        "hwid_status": hwid_val,
                        "used_by_ip": k.get("used_by_ip", ""),
                        "used_at": k.get("used_at", ""),
                        "created_at": k.get("created_at", "")
                    })
                elif isinstance(k, str):
                    remote_keys.append({
                        "key": k,
                        "duration": "30 Days",
                        "note": f"AuthZen ({seller_k})",
                        "status": "Unused",
                        "hwid": "None",
                        "created_at": ""
                    })
    except Exception as e:
        print(f"[AUTHZEN KEYS FETCH NOTE] {e}")

    # Merge unique keys
    seen = set()
    combined = []
    for item in logged_keys:
        k = item.get("key")
        if k and k not in seen:
            seen.add(k)
            combined.append(item)
    for item in remote_keys:
        k = item.get("key")
        if k and k not in seen:
            seen.add(k)
            combined.append(item)

    if status and status.lower() != "all":
        combined = [x for x in combined if (x.get("status") or "").lower() == status.lower()]
    if search:
        s = search.lower()
        combined = [x for x in combined if s in (x.get("key") or "").lower() or s in (x.get("note") or "").lower()]

    return jsonify({
        "success": True,
        "count": len(combined),
        "licenses": combined
    }), 200


# 2. Get Single License
@app.route('/api/authcloud/licenses/<path:key_or_id>', methods=['GET'])
def authcloud_get_single_license(key_or_id):
    # Check local logs first
    if license_keys_log_col is not None:
        try:
            doc = license_keys_log_col.find_one({"keys": key_or_id}, {"_id": 0})
            if doc:
                return jsonify({
                    "success": True,
                    "license": {
                        "key": key_or_id,
                        "duration": doc.get("duration", "—"),
                        "note": doc.get("note", f"Generated by {doc.get('reseller', 'Admin')}"),
                        "status": "Unused",
                        "hwid": "None",
                        "created_at": doc.get("created_at", "")
                    }
                }), 200
        except Exception:
            pass

    return jsonify({
        "success": True,
        "license": {
            "key": key_or_id,
            "duration": "Active",
            "note": "AuthZen License Key",
            "status": "Unused",
            "hwid": "Not Bound",
            "created_at": datetime.utcnow().isoformat()
        }
    }), 200


# 3. Create License Key(s) via https://brmodsbypass.authzen.site/api/get-key
# Strict Reseller Expiration Date & Allowed Duration Enforcement
@app.route('/api/authcloud/licenses/create', methods=['POST'])
def authcloud_create_licenses():
    body = request.json or {}
    admin_key = body.get("admin_key", "").strip()
    username  = body.get("username", "").strip()
    password  = body.get("password", "").strip()

    duration   = body.get("duration", "30 Days").strip()
    note       = body.get("note", "Dashboard Order").strip()
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
        if not reseller_doc and subadmins_col is not None:
            sub = subadmins_col.find_one({"username": username, "password": password})
            if sub:
                reseller_doc = {
                    "username": username,
                    "password": password,
                    "note": sub.get("note", "Subadmin Reseller"),
                    "key_limit": sub.get("key_limit", sub.get("credits", 20)),
                    "keys_used": sub.get("keys_used", 0),
                    "expiry_date": "",
                    "allowed_durations": ["all"],
                    "created_at": datetime.utcnow().isoformat()
                }
                save_key_reseller_doc(reseller_doc)

        if not reseller_doc or reseller_doc.get("password") != password:
            return jsonify({"success": False, "status": "error", "message": "Invalid reseller credentials"}), 403

        # 1. Reseller Account Validity Expiry Date Check
        reseller_exp = reseller_doc.get("expiry_date", "").strip()
        if reseller_exp:
            try:
                exp_dt = datetime.strptime(reseller_exp[:10], "%Y-%m-%d")
                now_dt = datetime.utcnow()
                if now_dt > (exp_dt + timedelta(days=1)):
                    return jsonify({
                        "success": False,
                        "status": "account_expired",
                        "message": f"❌ Your Reseller Account expired on {reseller_exp[:10]}. Key generation is disabled. Contact Admin to extend your account validity.",
                        "expiry_date": reseller_exp
                    }), 403
            except Exception as e:
                print(f"[EXP DATE PARSE ERR] {e}")

        # 2. Reseller Allowed Key Duration ("Kotodin er key generate korte parbe") Check
        allowed = reseller_doc.get("allowed_durations", ["all"])
        if isinstance(allowed, str):
            allowed_list = [x.strip() for x in allowed.split(",") if x.strip()]
        else:
            allowed_list = [str(x).strip() for x in allowed if str(x).strip()]

        if allowed_list and "all" not in [x.lower() for x in allowed_list] and "*" not in allowed_list:
            def norm_d(d):
                return d.lower().replace(" ", "").replace("s", "").replace("(1year)", "")
            req_norm = norm_d(duration)
            allowed_norms = [norm_d(x) for x in allowed_list]
            if req_norm not in allowed_norms:
                return jsonify({
                    "success": False,
                    "status": "duration_not_allowed",
                    "message": f"❌ You are not permitted to generate '{duration}' keys. Admin has restricted your account to: {', '.join(allowed_list)}.",
                    "allowed_durations": allowed_list
                }), 403

        # 3. Quota Verification: check remaining key limit
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

    # Get active Seller Key for AuthZen API
    active_seller_key = (reseller_doc.get("seller_key") or "").strip() if reseller_doc else ""
    if not active_seller_key:
        active_seller_key = get_authzen_seller_key()

    creator_tag = f"Reseller: {username}" if reseller_doc else "Master Admin"
    full_note = f"{note} [{creator_tag}]" if note else creator_tag

    # Map duration to standard AuthZen plan code (e.g. 1day, 3day, 7day, 15day, 30day, 60day, 90day, 365day)
    dur_clean = duration.lower().strip()
    plan_map = {
        "1 hour": "1hour",
        "2 hours": "2hour",
        "12 hours": "12hour",
        "1 day": "1day",
        "3 days": "3day",
        "7 days": "7day",
        "15 days": "15day",
        "30 days": "30day",
        "60 days": "60day",
        "90 days": "90day",
        "365 days": "365day",
        "lifetime": "365day"
    }
    plan_code = plan_map.get(dur_clean)
    if not plan_code:
        import re
        nums = re.findall(r'\d+', dur_clean)
        if nums:
            if "hour" in dur_clean:
                plan_code = f"{nums[0]}hour"
            else:
                plan_code = f"{nums[0]}day"
        else:
            plan_code = "30day"

    generated_keys = []
    api_err = None

    # Step A: Call GET https://brmodsbypass.authzen.site/api/get-key?seller_key=...&plan=...
    for _ in range(count):
        try:
            resp = requests.get(
                f"{AUTHCLOUD_API_BASE}/get-key?seller_key={active_seller_key}&plan={plan_code}",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=20
            )
            if resp.status_code in (200, 201):
                try:
                    res_data = resp.json()
                    if isinstance(res_data, dict):
                        k_str = res_data.get("key")
                        if k_str:
                            generated_keys.append({
                                "key": k_str,
                                "duration": f"{res_data.get('days', duration)} Days" if res_data.get('days') else duration,
                                "plan": res_data.get("plan", plan_code),
                                "note": full_note,
                                "status": "Unused",
                                "hwid": "None",
                                "created_at": res_data.get("issued_at", datetime.utcnow().isoformat())
                            })
                        elif "licenses" in res_data and isinstance(res_data["licenses"], list):
                            generated_keys.extend(res_data["licenses"])
                        elif "keys" in res_data and isinstance(res_data["keys"], list):
                            generated_keys.extend([{"key": k, "duration": duration, "note": full_note} for k in res_data["keys"]])
                        else:
                            api_err = res_data.get("message") or "No key returned in API response"
                except Exception as ex:
                    api_err = f"JSON parse error: {ex}"
            else:
                try:
                    err_data = resp.json()
                    api_err = err_data.get("message") or err_data.get("error")
                except Exception:
                    api_err = f"HTTP {resp.status_code}"
                break
        except Exception as e:
            api_err = str(e)
            break

    if not generated_keys:
        msg = f"Failed to generate key from AuthZen API ({AUTHZEN_GET_KEY_URL}): {api_err or 'No key returned'}"
        if not active_seller_key or "seller key" in (api_err or "").lower():
            msg += ". Please configure a valid AuthZen Seller Key in License Hub Settings."
        return jsonify({
            "success": False,
            "status": "error",
            "message": msg,
            "api_error": api_err
        }), 400

    actual_count = len(generated_keys)
    new_used = 0

    if reseller_doc:
        new_used = int(reseller_doc.get("keys_used", 0)) + actual_count
        reseller_doc["keys_used"] = new_used
        save_key_reseller_doc(reseller_doc)

    key_codes = [k.get("key") if isinstance(k, dict) else str(k) for k in generated_keys]
    log_entry = {
        "reseller": username if reseller_doc else "Master Admin",
        "count": actual_count,
        "duration": duration,
        "keys": key_codes,
        "note": full_note,
        "created_at": datetime.utcnow().isoformat()
    }
    if license_keys_log_col is not None:
        try:
            license_keys_log_col.insert_one(log_entry.copy())
        except Exception as e:
            print(f"[KEY LOG ERR] {e}")
    save_license_keys_local_log(log_entry)

    response_data = {
        "success": True,
        "message": f"Successfully created {actual_count} license key(s) via AuthZen API!",
        "licenses": [{"key": k, "duration": duration, "note": full_note, "status": "Unused"} for k in key_codes]
    }
    if reseller_doc:
        response_data["reseller_quota"] = {
            "key_limit": int(reseller_doc.get("key_limit", 0)),
            "keys_used": new_used,
            "remaining": max(0, int(reseller_doc.get("key_limit", 0)) - new_used)
        }
    return jsonify(response_data), 200


# 1. Create License Key Direct Route (AuthZen Engine)
# curl -X GET "https://brmodsbypass.authzen.site/api/get-key?seller_key=RES-E961EF9C&plan=30day"
@app.route('/api/get-key', methods=['GET'])
def authcloud_direct_get_key():
    seller_key = request.args.get("seller_key", "").strip() or get_authzen_seller_key()
    plan = request.args.get("plan", "30day").strip()
    try:
        url = f"{AUTHCLOUD_API_BASE}/get-key?seller_key={seller_key}&plan={plan}"
        resp = requests.get(url, timeout=15)
        try:
            return jsonify(resp.json()), resp.status_code
        except Exception:
            return jsonify({"success": resp.status_code == 200, "message": resp.text}), resp.status_code
    except Exception as e:
        return jsonify({"success": False, "message": f"AuthZen API error: {e}"}), 500


# 2. Reset HWID
# curl -X POST "https://brmodsbypass.authzen.site/api/key/reset?seller_key=RES-E961EF9C&key=BYP-XXXX-XXXX"
@app.route('/api/key/reset', methods=['POST', 'GET'])
@app.route('/api/authcloud/licenses/reset-hwid', methods=['POST'])
def authcloud_reset_hwid():
    body = request.get_json(silent=True) or {}
    key = (request.args.get("key") or body.get("key") or "").strip()
    seller_key = (request.args.get("seller_key") or body.get("seller_key") or "").strip() or get_authzen_seller_key()
    if not key:
        return jsonify({"success": False, "message": "Key is required to reset HWID"}), 400
    try:
        url = f"{AUTHCLOUD_API_BASE}/key/reset?seller_key={seller_key}&key={key}"
        resp = requests.post(url, timeout=15)
        try:
            return jsonify(resp.json()), resp.status_code
        except Exception:
            return jsonify({"success": resp.status_code == 200, "message": resp.text}), resp.status_code
    except Exception as e:
        return jsonify({"success": False, "message": f"AuthZen API error: {e}"}), 500


# 3. Unlock HWID
# curl -X POST "https://brmodsbypass.authzen.site/api/key/unlock?seller_key=RES-E961EF9C&key=BYP-XXXX-XXXX"
@app.route('/api/key/unlock', methods=['POST', 'GET'])
@app.route('/api/authcloud/licenses/unlock-hwid', methods=['POST'])
def authcloud_unlock_hwid():
    body = request.get_json(silent=True) or {}
    key = (request.args.get("key") or body.get("key") or "").strip()
    seller_key = (request.args.get("seller_key") or body.get("seller_key") or "").strip() or get_authzen_seller_key()
    if not key:
        return jsonify({"success": False, "message": "Key is required to unlock HWID"}), 400
    try:
        url = f"{AUTHCLOUD_API_BASE}/key/unlock?seller_key={seller_key}&key={key}"
        resp = requests.post(url, timeout=15)
        try:
            return jsonify(resp.json()), resp.status_code
        except Exception:
            return jsonify({"success": resp.status_code == 200, "message": resp.text}), resp.status_code
    except Exception as e:
        return jsonify({"success": False, "message": f"AuthZen API error: {e}"}), 500


# 4. Ban Key
# curl -X POST "https://brmodsbypass.authzen.site/api/key/ban?seller_key=RES-E961EF9C&key=BYP-XXXX-XXXX"
@app.route('/api/key/ban', methods=['POST', 'GET'])
@app.route('/api/authcloud/licenses/ban', methods=['POST'])
def authcloud_ban_license():
    body = request.get_json(silent=True) or {}
    key = (request.args.get("key") or body.get("key") or "").strip()
    seller_key = (request.args.get("seller_key") or body.get("seller_key") or "").strip() or get_authzen_seller_key()
    if not key:
        return jsonify({"success": False, "message": "Key is required to ban"}), 400
    try:
        url = f"{AUTHCLOUD_API_BASE}/key/ban?seller_key={seller_key}&key={key}"
        resp = requests.post(url, timeout=15)
        try:
            return jsonify(resp.json()), resp.status_code
        except Exception:
            return jsonify({"success": resp.status_code == 200, "message": resp.text}), resp.status_code
    except Exception as e:
        return jsonify({"success": False, "message": f"AuthZen API error: {e}"}), 500


# 5. Unban Key
# curl -X POST "https://brmodsbypass.authzen.site/api/key/unban?seller_key=RES-E961EF9C&key=BYP-XXXX-XXXX"
@app.route('/api/key/unban', methods=['POST', 'GET'])
@app.route('/api/authcloud/licenses/unban', methods=['POST'])
def authcloud_unban_license():
    body = request.get_json(silent=True) or {}
    key = (request.args.get("key") or body.get("key") or "").strip()
    seller_key = (request.args.get("seller_key") or body.get("seller_key") or "").strip() or get_authzen_seller_key()
    if not key:
        return jsonify({"success": False, "message": "Key is required to unban"}), 400
    try:
        url = f"{AUTHCLOUD_API_BASE}/key/unban?seller_key={seller_key}&key={key}"
        resp = requests.post(url, timeout=15)
        try:
            return jsonify(resp.json()), resp.status_code
        except Exception:
            return jsonify({"success": resp.status_code == 200, "message": resp.text}), resp.status_code
    except Exception as e:
        return jsonify({"success": False, "message": f"AuthZen API error: {e}"}), 500


# 6. Delete Key
# curl -X POST "https://brmodsbypass.authzen.site/api/key/delete?seller_key=RES-E961EF9C&key=BYP-XXXX-XXXX"
@app.route('/api/key/delete', methods=['POST', 'GET'])
@app.route('/api/authcloud/licenses/delete', methods=['POST'])
def authcloud_delete_license():
    body = request.get_json(silent=True) or {}
    key = (request.args.get("key") or body.get("key") or "").strip()
    seller_key = (request.args.get("seller_key") or body.get("seller_key") or "").strip() or get_authzen_seller_key()
    if not key:
        return jsonify({"success": False, "message": "Key is required to delete"}), 400
    try:
        url = f"{AUTHCLOUD_API_BASE}/key/delete?seller_key={seller_key}&key={key}"
        resp = requests.post(url, timeout=15)
        try:
            return jsonify(resp.json()), resp.status_code
        except Exception:
            return jsonify({"success": resp.status_code == 200, "message": resp.text}), resp.status_code
    except Exception as e:
        return jsonify({"success": False, "message": f"AuthZen API error: {e}"}), 500


# 7. List Your Keys
# curl -X GET "https://brmodsbypass.authzen.site/api/key/list?seller_key=RES-E961EF9C"
@app.route('/api/key/list', methods=['GET'])
def authcloud_direct_list_keys():
    seller_key = request.args.get("seller_key", "").strip() or get_authzen_seller_key()
    try:
        url = f"{AUTHCLOUD_API_BASE}/key/list?seller_key={seller_key}"
        resp = requests.get(url, timeout=15)
        try:
            return jsonify(resp.json()), resp.status_code
        except Exception:
            return jsonify({"success": resp.status_code == 200, "message": resp.text}), resp.status_code
    except Exception as e:
        return jsonify({"success": False, "message": f"AuthZen API error: {e}"}), 500


# 7. Reseller Management — List All Resellers with Quota, Expiry Date & Allowed Durations (Admin Only)
@app.route('/api/authcloud/resellers', methods=['GET'])
def authcloud_list_resellers():
    admin_key = request.args.get("admin_key", "").strip()
    if admin_key != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Unauthorized admin access"}), 403

    resellers = get_all_key_resellers()
    output = []
    now_dt = datetime.utcnow()
    for r in resellers:
        lim = int(r.get("key_limit", 0))
        usd = int(r.get("keys_used", 0))
        exp = r.get("expiry_date", "")
        is_expired = False
        days_left = None
        if exp:
            try:
                exp_dt = datetime.strptime(exp[:10], "%Y-%m-%d")
                delta = (exp_dt - now_dt).days
                days_left = max(0, delta)
                if delta < 0:
                    is_expired = True
            except Exception:
                pass

        output.append({
            "username": r.get("username"),
            "note": r.get("note", ""),
            "key_limit": lim,
            "keys_used": usd,
            "remaining": max(0, lim - usd),
            "expiry_date": exp,
            "is_expired": is_expired,
            "days_left": days_left,
            "allowed_durations": r.get("allowed_durations", ["all"]),
            "seller_key": r.get("seller_key", ""),
            "created_at": r.get("created_at", "")
        })
    return jsonify({"status": "success", "resellers": output, "total": len(output)}), 200


# 8. Reseller Management — Create Reseller with Quota, Expiry Date & Allowed Durations (Admin Only)
@app.route('/api/authcloud/resellers/create', methods=['POST'])
def authcloud_create_reseller():
    body = request.json or {}
    admin_key = body.get("admin_key", "").strip()
    if admin_key != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Unauthorized admin access"}), 403

    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    note     = body.get("note", "").strip()
    try:
        key_limit = int(body.get("key_limit", 20))
    except (ValueError, TypeError):
        key_limit = 20

    expiry_date = body.get("expiry_date", "").strip()
    allowed_durations = body.get("allowed_durations", ["all"])
    if isinstance(allowed_durations, str):
        allowed_durations = [x.strip() for x in allowed_durations.split(",") if x.strip()]
    if not allowed_durations:
        allowed_durations = ["all"]

    seller_key = body.get("seller_key", "").strip()

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
        "expiry_date": expiry_date,
        "allowed_durations": allowed_durations,
        "seller_key": seller_key,
        "created_at": datetime.utcnow().isoformat()
    }
    save_key_reseller_doc(reseller_doc)

    return jsonify({
        "status": "success",
        "message": f"Reseller '{username}' created successfully",
        "reseller": {
            "username": username,
            "key_limit": key_limit,
            "keys_used": 0,
            "remaining": key_limit,
            "expiry_date": expiry_date,
            "allowed_durations": allowed_durations
        }
    }), 200


# 9. Reseller Management — Update Limit, Expiry Date & Allowed Durations (Admin Only)
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

    if "expiry_date" in body:
        reseller["expiry_date"] = str(body["expiry_date"]).strip()

    if "allowed_durations" in body:
        durs = body["allowed_durations"]
        if isinstance(durs, str):
            durs = [x.strip() for x in durs.split(",") if x.strip()]
        reseller["allowed_durations"] = durs if durs else ["all"]

    if "seller_key" in body:
        reseller["seller_key"] = str(body["seller_key"]).strip()

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
        "message": f"Reseller '{username}' quota and dates updated successfully",
        "reseller": {
            "username": username,
            "key_limit": lim,
            "keys_used": usd,
            "remaining": max(0, lim - usd),
            "expiry_date": reseller.get("expiry_date", ""),
            "allowed_durations": reseller.get("allowed_durations", ["all"])
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
    exp = reseller.get("expiry_date", "")
    is_expired = False
    days_left = None
    if exp:
        try:
            exp_dt = datetime.strptime(exp[:10], "%Y-%m-%d")
            delta = (exp_dt - datetime.utcnow()).days
            days_left = max(0, delta)
            if delta < 0:
                is_expired = True
        except Exception:
            pass

    return jsonify({
        "status": "success",
        "username": username,
        "note": reseller.get("note", ""),
        "key_limit": lim,
        "keys_used": usd,
        "remaining": max(0, lim - usd),
        "expiry_date": exp,
        "is_expired": is_expired,
        "days_left": days_left,
        "allowed_durations": reseller.get("allowed_durations", ["all"])
    }), 200


# 12. Master Admin — AuthZen Seller Key Setting
@app.route('/api/authcloud/settings/seller-key', methods=['GET', 'POST'])
def authcloud_seller_key_setting():
    if request.method == 'GET':
        admin_key = request.args.get("admin_key", "").strip()
        if admin_key != ADMIN_KEY:
            return jsonify({"status": "error", "message": "Unauthorized"}), 403
        curr_key = get_authzen_seller_key()
        masked = (curr_key[:4] + "..." + curr_key[-4:]) if len(curr_key) > 8 else (curr_key if curr_key else "")
        return jsonify({
            "status": "success",
            "seller_key": curr_key,
            "masked_key": masked,
            "configured": bool(curr_key),
            "api_url": AUTHZEN_GET_KEY_URL
        }), 200

    body = request.json or {}
    admin_key = body.get("admin_key", "").strip()
    if admin_key != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    new_seller_key = body.get("seller_key", "").strip()
    set_authzen_seller_key(new_seller_key)
    return jsonify({
        "status": "success",
        "message": "AuthZen Seller Key updated successfully!",
        "configured": bool(new_seller_key)
    }), 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8002))
    app.run(host='0.0.0.0', port=port, debug=False)

