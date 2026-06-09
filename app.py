import os
import requests
import threading
import time
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime, timedelta

load_dotenv()

app = Flask(__name__)

# CONFIG
SENSIX_BASE   = os.environ.get("SENSIX_BASE", "http://new.sensix.shop:2005")
SENSIX_APIKEY = os.environ.get("SENSIX_APIKEY", "SENSIX-B09BB8CDC3627617B9DD8CF0D7F9674A6F11E82311F89930")
ADMIN_KEY     = os.environ.get("ADMIN_KEY", "changeme_admin_key")
SELF_URL      = os.environ.get("SELF_URL", "")  # e.g. https://your-app.onrender.com

# MONGODB SETUP
MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://NAYEM:1122@cluster0.ywmyozb.mongodb.net/?appName=Cluster0")
try:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000, tls=True, tlsAllowInvalidCertificates=True)
    mongo_client.server_info()
    db = mongo_client["sensix_panel"]
    subadmins_col    = db["subadmins"]
    uid_ownership_col = db["uid_ownership"]
    print("MongoDB connected OK")
except Exception as e:
    print(f"MongoDB FAILED: {e}")
    mongo_client      = None
    db                = None
    subadmins_col     = None
    uid_ownership_col = None

SENSIX_HEADERS = {
    "X-AUTH-KEY": SENSIX_APIKEY,
    "Content-Type": "application/json"
}

def sensix(method, path, **kwargs):
    url = f"{SENSIX_BASE}{path}"
    try:
        r = requests.request(method, url, headers=SENSIX_HEADERS, timeout=20, **kwargs)
        try:
            return r.json(), r.status_code
        except Exception:
            return {"error": r.text}, r.status_code
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}, 503


# ===== SELF PING (Render sleep prevention) =====
def self_ping():
    """Every 5 minutes ping self to prevent Render from sleeping"""
    while True:
        time.sleep(300)  # 5 minutes
        if SELF_URL:
            try:
                requests.get(SELF_URL + "/ping", timeout=10)
                print(f"[SELF-PING] OK — {datetime.utcnow().strftime('%H:%M:%S')}")
            except Exception as e:
                print(f"[SELF-PING] Failed: {e}")

ping_thread = threading.Thread(target=self_ping, daemon=True)
ping_thread.start()

@app.route('/ping')
def ping():
    return jsonify({"status": "alive", "time": datetime.utcnow().isoformat()}), 200


# ===== HELPERS =====
def merge_expiry(uids):
    """Merge expires_at from MongoDB into UID list"""
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
    """Save or update UID metadata (expires_at) in MongoDB"""
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
            "uid": uid,
            "name": name,
            "days": days,
            "owner": owner,
            "expires_at": new_exp.isoformat(),
            "added_at": datetime.utcnow().isoformat()
        }},
        upsert=True
    )


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
    data, code = sensix("GET", "/api/v1/uids/list")
    if code != 200:
        return jsonify({"status": "error", "message": data.get("error", "Sensix error")}), code
    uids = data if isinstance(data, list) else data.get("uids", data.get("data", []))
    uids = [u for u in uids if u.get("status", "active") != "removed"]
    uids = merge_expiry(uids)
    return jsonify({"status": "success", "total": len(uids), "licenses": uids}), 200


# ===== ADMIN — CREATE =====
@app.route('/admin/create', methods=['POST'])
def admin_create():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    uid  = body.get("uid", "").strip()
    days = int(body.get("days", 30))
    name = body.get("name", "Player").strip()
    if not uid:
        return jsonify({"status": "error", "message": "uid required"}), 400
    data, code = sensix("POST", "/api/v1/uids/add", json={"uid": uid, "days": days, "name": name})
    if code in (200, 201):
        save_uid_meta(uid, name, days, owner="main_admin", extend=False)
        return jsonify({"status": "success", "message": "UID added", "data": data}), 200
    return jsonify({"status": "error", "message": data.get("message", data.get("error", "Sensix error"))}), code


# ===== ADMIN — REVOKE =====
@app.route('/admin/revoke', methods=['POST'])
def admin_revoke():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    uid = body.get("uid", "").strip()
    if not uid:
        return jsonify({"status": "error", "message": "uid required"}), 400
    data, code = sensix("POST", "/api/v1/uids/remove", json={"uid": uid})
    if uid_ownership_col is not None:
        uid_ownership_col.delete_one({"uid": uid})
    if code == 200:
        return jsonify({"status": "success", "message": f"UID {uid} removed"}), 200
    return jsonify({"status": "error", "message": data.get("message", data.get("error", "Sensix error"))}), code


# ===== ADMIN — UPDATE/RENEW =====
@app.route('/admin/update', methods=['POST'])
def admin_update():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    uid  = body.get("uid", "").strip()
    days = int(body.get("days", 30))
    if not uid:
        return jsonify({"status": "error", "message": "uid required"}), 400
    data, code = sensix("POST", f"/api/v1/uids/{uid}/renew", json={"days": days})
    if code in (200, 201):
        # Get existing name
        existing_name = "Player"
        if uid_ownership_col is not None:
            doc = uid_ownership_col.find_one({"uid": uid})
            if doc:
                existing_name = doc.get("name", "Player")
        save_uid_meta(uid, existing_name, days, extend=True)
        return jsonify({"status": "success", "message": f"UID {uid} renewed {days}d", "data": data}), 200
    return jsonify({"status": "error", "message": data.get("message", data.get("error", "Sensix error"))}), code


# ===== SUB-ADMIN MANAGEMENT =====
@app.route('/admin/create-subadmin', methods=['POST'])
def create_subadmin():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if subadmins_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    note     = body.get("note", "").strip()
    if not username or not password:
        return jsonify({"status": "error", "message": "username and password required"}), 400
    if subadmins_col.find_one({"username": username}):
        return jsonify({"status": "error", "message": "Username already exists"}), 409
    subadmins_col.insert_one({
        "username": username,
        "password": password,
        "note": note,
        "created_at": datetime.utcnow()
    })
    return jsonify({"status": "success", "message": f"Sub-admin '{username}' created"}), 200


@app.route('/admin/list-subadmins', methods=['GET'])
def list_subadmins():
    if request.args.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if subadmins_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500
    result = [
        {"username": sa["username"], "note": sa.get("note", ""), "active": True}
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
    result = subadmins_col.delete_one({"username": username})
    if result.deleted_count == 0:
        return jsonify({"status": "error", "message": "Sub-admin not found"}), 404
    return jsonify({"status": "success", "message": f"Sub-admin '{username}' deleted"}), 200


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


# ===== SUB-ADMIN — LIST =====
@app.route('/subadmin/list', methods=['GET'])
def subadmin_list():
    username = request.args.get("username", "")
    password = request.args.get("password", "")
    if not verify_subadmin(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    data, code = sensix("GET", "/api/v1/uids/list")
    if code != 200:
        return jsonify({"status": "error", "message": data.get("error", "Sensix error")}), code
    all_uids = data if isinstance(data, list) else data.get("uids", data.get("data", []))
    all_uids = [u for u in all_uids if u.get("status", "active") != "removed"]
    if uid_ownership_col is not None:
        owned = set(
            doc["uid"] for doc in uid_ownership_col.find({"owner": username}, {"uid": 1})
        )
        my_uids = [u for u in all_uids if (u.get("uid") or u.get("id") or "") in owned]
    else:
        my_uids = all_uids
    my_uids = merge_expiry(my_uids)
    return jsonify({"status": "success", "total": len(my_uids), "licenses": my_uids}), 200


# ===== SUB-ADMIN — CREATE =====
@app.route('/subadmin/create', methods=['POST'])
def subadmin_create():
    body = request.json or {}
    username = body.get("username", "")
    password = body.get("password", "")
    if not verify_subadmin(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    uid  = body.get("uid", "").strip()
    days = int(body.get("days", 30))
    name = body.get("name", "Player").strip()
    if not uid:
        return jsonify({"status": "error", "message": "uid required"}), 400
    data, code = sensix("POST", "/api/v1/uids/add", json={"uid": uid, "days": days, "name": name})
    if code in (200, 201):
        save_uid_meta(uid, name, days, owner=username, extend=False)
        return jsonify({"status": "success", "message": "UID added", "data": data}), 200
    return jsonify({"status": "error", "message": data.get("message", data.get("error", "Sensix error"))}), code


# ===== SUB-ADMIN — REVOKE =====
@app.route('/subadmin/revoke', methods=['POST'])
def subadmin_revoke():
    body = request.json or {}
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
    data, code = sensix("POST", "/api/v1/uids/remove", json={"uid": uid})
    if uid_ownership_col is not None:
        uid_ownership_col.delete_one({"uid": uid})
    if code == 200:
        return jsonify({"status": "success", "message": f"UID {uid} removed"}), 200
    return jsonify({"status": "error", "message": data.get("message", data.get("error", "Sensix error"))}), code


# ===== SUB-ADMIN — UPDATE/RENEW =====
@app.route('/subadmin/update', methods=['POST'])
def subadmin_update():
    body = request.json or {}
    username = body.get("username", "")
    password = body.get("password", "")
    if not verify_subadmin(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    uid  = body.get("uid", "").strip()
    days = int(body.get("days", 30))
    if not uid:
        return jsonify({"status": "error", "message": "uid required"}), 400
    data, code = sensix("POST", f"/api/v1/uids/{uid}/renew", json={"days": days})
    if code in (200, 201):
        existing_name = "Player"
        if uid_ownership_col is not None:
            doc = uid_ownership_col.find_one({"uid": uid})
            if doc:
                existing_name = doc.get("name", "Player")
        save_uid_meta(uid, existing_name, days, owner=username, extend=True)
        return jsonify({"status": "success", "message": f"UID {uid} renewed {days}d", "data": data}), 200
    return jsonify({"status": "error", "message": data.get("message", data.get("error", "Sensix error"))}), code


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
