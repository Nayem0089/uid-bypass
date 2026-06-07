import os
import requests
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime

load_dotenv()

app = Flask(__name__)

# CONFIG
SENSIX_BASE   = os.environ.get("SENSIX_BASE", "http://new.sensix.shop:2005")
SENSIX_APIKEY = os.environ.get("SENSIX_APIKEY", "SENSIX-6E1D04F888A3CC09C952D58EE63971C919D777C43EB90B5E")
ADMIN_KEY     = os.environ.get("ADMIN_KEY", "changeme_admin_key")

# MONGODB SETUP
MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://NAYEM:1122@cluster0.ywmyozb.mongodb.net/?appName=Cluster0")
try:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000, tls=True, tlsAllowInvalidCertificates=True)
    mongo_client.server_info()
    db = mongo_client["sensix_panel"]
    subadmins_col = db["subadmins"]
    uid_ownership_col = db["uid_ownership"]  # tracks which reseller added which UID
    print("MongoDB connected OK")
except Exception as e:
    print(f"MongoDB FAILED: {e}")
    mongo_client = None
    db = None
    subadmins_col = None
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


# FRONTEND
@app.route('/')
def index():
    return render_template('index.html')


# MAIN ADMIN AUTH
@app.route('/admin/verify', methods=['POST'])
def admin_verify():
    data = request.json or {}
    if data.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    return jsonify({"status": "success", "role": "main_admin"}), 200


# LICENSES - MAIN ADMIN
@app.route('/admin/list', methods=['GET'])
def admin_list():
    if request.args.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    data, code = sensix("GET", "/api/v1/uids/list")
    if code != 200:
        return jsonify({"status": "error", "message": data.get("error", "Sensix error")}), code
    uids = data if isinstance(data, list) else data.get("uids", data.get("data", []))
    return jsonify({"status": "success", "total": len(uids), "licenses": uids}), 200


@app.route('/admin/create', methods=['POST'])
def admin_create():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    payload = {
        "uid":  body.get("uid", "").strip(),
        "days": int(body.get("days", 30)),
        "name": body.get("name", "Player").strip()
    }
    if not payload["uid"]:
        return jsonify({"status": "error", "message": "uid required"}), 400
    data, code = sensix("POST", "/api/v1/uids/add", json=payload)
    if code in (200, 201):
        return jsonify({"status": "success", "message": "UID added", "data": data}), 200
    return jsonify({"status": "error", "message": data.get("message", data.get("error", "Sensix error"))}), code


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
        return jsonify({"status": "success", "message": f"UID {uid} renewed {days}d", "data": data}), 200
    return jsonify({"status": "error", "message": data.get("message", data.get("error", "Sensix error"))}), code


# SUB-ADMIN MANAGEMENT
@app.route('/admin/create-subadmin', methods=['POST'])
def create_subadmin():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if subadmins_col is None:
        return jsonify({"status": "error", "message": "Database not connected. Check MONGO_URI in environment variables."}), 500
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


# SUB-ADMIN LOGIN + UID ACTIONS
def verify_subadmin(username, password):
    if subadmins_col is None:
        return False
    sa = subadmins_col.find_one({"username": username, "password": password})
    return sa is not None


@app.route('/subadmin/login', methods=['POST'])
def subadmin_login():
    body = request.json or {}
    if verify_subadmin(body.get("username", ""), body.get("password", "")):
        return jsonify({"status": "success", "role": "sub_admin", "username": body["username"]}), 200
    return jsonify({"status": "error", "message": "Invalid credentials"}), 403


@app.route('/subadmin/list', methods=['GET'])
def subadmin_list():
    """Reseller শুধু নিজের add করা UIDs দেখবে"""
    username = request.args.get("username", "")
    password = request.args.get("password", "")
    if not verify_subadmin(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    # Get all UIDs from Sensix
    data, code = sensix("GET", "/api/v1/uids/list")
    if code != 200:
        return jsonify({"status": "error", "message": data.get("error", "Sensix error")}), code
    all_uids = data if isinstance(data, list) else data.get("uids", data.get("data", []))

    # Filter only UIDs owned by this reseller
    if uid_ownership_col is not None:
        owned = set(
            doc["uid"] for doc in uid_ownership_col.find({"owner": username}, {"uid": 1})
        )
        my_uids = [u for u in all_uids if (u.get("uid") or u.get("id") or "") in owned]
    else:
        my_uids = all_uids  # fallback: show all if DB not available

    return jsonify({"status": "success", "total": len(my_uids), "licenses": my_uids}), 200


@app.route('/subadmin/create', methods=['POST'])
def subadmin_create():
    body = request.json or {}
    username = body.get("username", "")
    password = body.get("password", "")
    if not verify_subadmin(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    payload = {
        "uid":  body.get("uid", "").strip(),
        "days": int(body.get("days", 30)),
        "name": body.get("name", "Player").strip()
    }
    if not payload["uid"]:
        return jsonify({"status": "error", "message": "uid required"}), 400
    data, code = sensix("POST", "/api/v1/uids/add", json=payload)
    if code in (200, 201):
        # Save ownership in MongoDB
        if uid_ownership_col is not None:
            uid_ownership_col.update_one(
                {"uid": payload["uid"]},
                {"$set": {"uid": payload["uid"], "owner": username, "added_at": datetime.utcnow()}},
                upsert=True
            )
        return jsonify({"status": "success", "message": "UID added", "data": data}), 200
    return jsonify({"status": "error", "message": data.get("message", data.get("error", "Sensix error"))}), code


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

    # Check ownership — reseller can only remove their own UIDs
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
        return jsonify({"status": "success", "message": f"UID {uid} renewed {days}d", "data": data}), 200
    return jsonify({"status": "error", "message": data.get("message", data.get("error", "Sensix error"))}), code


# DB STATUS CHECK
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
