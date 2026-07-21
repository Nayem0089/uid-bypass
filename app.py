import os
import requests
import threading
import time
import json
import logging
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.mongodb import MongoDBJobStore

load_dotenv()

app = Flask(__name__)
CORS(app)

# CONFIG
UID_API_BASE = os.environ.get("UID_API_BASE", "https://uid.syntaxcorporation.online")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "changeme_admin_key")
SELF_URL = os.environ.get("SELF_URL", "").rstrip("/")

# Auto Re-Add Configuration
AUTO_SUBMIT_ENABLED = os.environ.get("AUTO_SUBMIT_ENABLED", "true").lower() == "true"
AUTO_SUBMIT_INTERVAL = int(os.environ.get("AUTO_SUBMIT_INTERVAL", 7))  # hours
MAX_RETRY_ATTEMPTS = int(os.environ.get("MAX_RETRY_ATTEMPTS", 3))
RETRY_DELAY = int(os.environ.get("RETRY_DELAY", 60))  # seconds

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
    db = mongo_client["sensix_panel"]
    subadmins_col = db["subadmins"]
    fetchers_col = db["fetchers"]
    uid_ownership_col = db["uid_ownership"]
    credit_log_col = db["credit_log"]
    
    # Auto Re-Add Collections
    auto_submit_settings_col = db["auto_submit_settings"]
    auto_submit_logs_col = db["auto_submit_logs"]
    
    print("MongoDB connected OK")
except Exception as e:
    print(f"MongoDB FAILED: {e}")
    mongo_client = db = subadmins_col = fetchers_col = uid_ownership_col = credit_log_col = None
    auto_submit_settings_col = auto_submit_logs_col = None

# ============================================
# AUTO RE-ADD SYSTEM
# ============================================

class AutoReAddService:
    """Handles automatic re-submission of UIDs every 7 hours"""
    
    def __init__(self):
        self.scheduler = None
        self.job_id = 'auto_re_add_job'
        self.is_running = False
        
    def init_scheduler(self):
        """Initialize the APScheduler with MongoDB job store"""
        if self.scheduler:
            return
            
        try:
            # Configure MongoDB job store for persistence
            jobstores = {
                'default': MongoDBJobStore(
                    database='sensix_panel',
                    collection='scheduler_jobs',
                    client=mongo_client
                )
            }
            
            executors = {
                'default': ThreadPoolExecutor(max_workers=5)
            }
            
            job_defaults = {
                'coalesce': True,
                'max_instances': 1,
                'misfire_grace_time': 300
            }
            
            self.scheduler = BackgroundScheduler(
                jobstores=jobstores,
                executors=executors,
                job_defaults=job_defaults
            )
            
            # Add the auto-submit job
            self._schedule_job()
            
            # Start scheduler
            self.scheduler.start()
            print("Auto Re-Add scheduler started successfully")
            
        except Exception as e:
            print(f"Failed to initialize scheduler: {e}")
    
    def _schedule_job(self):
        """Schedule or reschedule the auto-submit job"""
        if not self.scheduler:
            return
            
        # Remove existing job if it exists
        if self.scheduler.get_job(self.job_id):
            self.scheduler.remove_job(self.job_id)
        
        # Get interval from settings
        interval = self._get_interval()
        
        # Add new job
        self.scheduler.add_job(
            func=self._run_auto_submit,
            trigger=IntervalTrigger(hours=interval),
            id=self.job_id,
            name='Auto Re-Add UIDs',
            replace_existing=True,
            misfire_grace_time=300,
            coalesce=True
        )
        
        print(f"Auto Re-Add job scheduled every {interval} hours")
    
    def _get_interval(self):
        """Get the current interval from database or environment"""
        try:
            if auto_submit_settings_col:
                settings = auto_submit_settings_col.find_one({"_id": "global"})
                if settings:
                    return settings.get("interval_hours", AUTO_SUBMIT_INTERVAL)
        except:
            pass
        return AUTO_SUBMIT_INTERVAL
    
    def _get_global_status(self):
        """Get global auto-submit status from database"""
        try:
            if auto_submit_settings_col:
                settings = auto_submit_settings_col.find_one({"_id": "global"})
                if settings:
                    return settings.get("enabled", AUTO_SUBMIT_ENABLED)
        except:
            pass
        return AUTO_SUBMIT_ENABLED
    
    def _run_auto_submit(self):
        """Main auto-submit execution function"""
        if self.is_running:
            print("Auto-submit already running, skipping...")
            return
            
        try:
            self.is_running = True
            
            # Check if global auto-submit is enabled
            if not self._get_global_status():
                print("Global auto-submit is disabled")
                return
            
            print(f"Starting auto re-add cycle at {datetime.utcnow().isoformat()}")
            
            # Get all UIDs that need re-submission
            uids_to_process = self._get_pending_uids()
            
            if not uids_to_process:
                print("No UIDs pending for re-submission")
                return
            
            print(f"Found {len(uids_to_process)} UIDs to process")
            
            results = {
                'processed': 0,
                'successful': 0,
                'failed': 0,
                'retries': 0
            }
            
            # Process each UID
            for uid_data in uids_to_process:
                success = self._process_uid(uid_data)
                results['processed'] += 1
                if success:
                    results['successful'] += 1
                else:
                    results['failed'] += 1
            
            # Log results
            self._log_auto_submit_results(results)
            
            print(f"Auto re-add cycle completed: {results}")
            
        except Exception as e:
            print(f"Error in auto-submit cycle: {e}")
            self._log_error(str(e))
        finally:
            self.is_running = False
    
    def _get_pending_uids(self):
        """Get all UIDs that are due for re-submission"""
        try:
            if uid_ownership_col is None:
                return []
            
            current_time = datetime.utcnow()
            
            # Get all UIDs that have auto-submit enabled and are due
            uids = list(uid_ownership_col.find({
                "$or": [
                    {"auto_submit_enabled": {"$ne": False}},
                    {"auto_submit_enabled": {"$exists": False}}
                ],
                "$or": [
                    {"next_auto_submit_time": {"$lte": current_time}},
                    {"next_auto_submit_time": {"$exists": False}},
                    {"last_auto_submit_time": {"$exists": False}}
                ],
                "status": {"$ne": "removed"}
            }))
            
            return uids
            
        except Exception as e:
            print(f"Error getting pending UIDs: {e}")
            return []
    
    def _process_uid(self, uid_data):
        """Process a single UID for re-submission"""
        uid = uid_data.get("uid")
        if not uid:
            return False
        
        try:
            # Prepare submission parameters
            days = uid_data.get("days", 1)
            
            # Submit to API
            success, response = self._submit_uid(uid, days)
            
            # Update UID metadata
            current_time = datetime.utcnow()
            interval = self._get_interval()
            
            update_data = {
                "last_auto_submit_time": current_time,
                "next_auto_submit_time": current_time + timedelta(hours=interval),
                "last_auto_submit_status": "success" if success else "failed"
            }
            
            if success:
                update_data["retry_count"] = 0
                update_data["status"] = "active"
            else:
                update_data["retry_count"] = uid_data.get("retry_count", 0) + 1
                if update_data["retry_count"] >= MAX_RETRY_ATTEMPTS:
                    update_data["status"] = "error"
            
            # Save updates to database
            uid_ownership_col.update_one(
                {"uid": uid},
                {"$set": update_data}
            )
            
            # Log the attempt
            self._log_submit_attempt(uid, success, response)
            
            return success
            
        except Exception as e:
            print(f"Error processing UID {uid}: {e}")
            return False
    
    def _submit_uid(self, uid, days=1):
        """Submit a UID to the third-party API"""
        try:
            url = f"{UID_API_BASE}/uid"
            params = {"add": uid, "days": days}
            
            # Retry logic
            for attempt in range(MAX_RETRY_ATTEMPTS):
                try:
                    response = requests.get(url, params=params, timeout=30)
                    
                    if response.status_code in (200, 201):
                        try:
                            return True, response.json()
                        except:
                            return True, {"message": response.text}
                    else:
                        # Check if it's a retry-worthy error
                        if response.status_code >= 500:
                            if attempt < MAX_RETRY_ATTEMPTS - 1:
                                time.sleep(RETRY_DELAY)
                                continue
                        return False, {"error": f"HTTP {response.status_code}: {response.text}"}
                        
                except requests.exceptions.Timeout:
                    if attempt < MAX_RETRY_ATTEMPTS - 1:
                        time.sleep(RETRY_DELAY)
                        continue
                    return False, {"error": "Request timeout"}
                    
                except requests.exceptions.ConnectionError:
                    if attempt < MAX_RETRY_ATTEMPTS - 1:
                        time.sleep(RETRY_DELAY)
                        continue
                    return False, {"error": "Connection error"}
                    
            return False, {"error": "Max retries exceeded"}
            
        except Exception as e:
            return False, {"error": str(e)}
    
    def _log_submit_attempt(self, uid, success, response):
        """Log individual UID submission attempt"""
        try:
            if auto_submit_logs_col is not None:
                log_entry = {
                    "uid": uid,
                    "timestamp": datetime.utcnow(),
                    "success": success,
                    "response": response,
                    "type": "auto_submit"
                }
                auto_submit_logs_col.insert_one(log_entry)
        except:
            pass
    
    def _log_auto_submit_results(self, results):
        """Log batch auto-submit results"""
        try:
            if auto_submit_logs_col is not None:
                log_entry = {
                    "type": "auto_submit_batch",
                    "timestamp": datetime.utcnow(),
                    "results": results,
                    "interval_hours": self._get_interval()
                }
                auto_submit_logs_col.insert_one(log_entry)
        except:
            pass
    
    def _log_error(self, error_message):
        """Log errors"""
        try:
            if auto_submit_logs_col is not None:
                log_entry = {
                    "type": "error",
                    "timestamp": datetime.utcnow(),
                    "error": error_message
                }
                auto_submit_logs_col.insert_one(log_entry)
        except:
            pass
    
    def force_run_now(self):
        """Manually trigger auto-submit"""
        try:
            # Run in a separate thread to not block
            thread = threading.Thread(target=self._run_auto_submit)
            thread.start()
            return True
        except Exception as e:
            print(f"Error forcing auto-submit: {e}")
            return False
    
    def update_interval(self, hours):
        """Update the auto-submit interval"""
        try:
            if auto_submit_settings_col:
                auto_submit_settings_col.update_one(
                    {"_id": "global"},
                    {"$set": {"interval_hours": hours}},
                    upsert=True
                )
            
            # Reschedule the job
            self._schedule_job()
            return True
        except Exception as e:
            print(f"Error updating interval: {e}")
            return False
    
    def set_global_status(self, enabled):
        """Enable or disable global auto-submit"""
        try:
            if auto_submit_settings_col:
                auto_submit_settings_col.update_one(
                    {"_id": "global"},
                    {"$set": {"enabled": enabled}},
                    upsert=True
                )
            return True
        except Exception as e:
            print(f"Error updating global status: {e}")
            return False
    
    def toggle_uid_auto_submit(self, uid, enabled):
        """Enable or disable auto-submit for a specific UID"""
        try:
            if uid_ownership_col:
                uid_ownership_col.update_one(
                    {"uid": uid},
                    {"$set": {"auto_submit_enabled": enabled}}
                )
            return True
        except Exception as e:
            print(f"Error toggling UID auto-submit: {e}")
            return False
    
    def get_stats(self):
        """Get auto-submit statistics"""
        try:
            stats = {
                "total_uids": 0,
                "active_uids": 0,
                "pending_submissions": 0,
                "successful_submissions": 0,
                "failed_submissions": 0,
                "total_processed": 0,
                "last_run_time": None,
                "next_run_time": None,
                "is_running": self.is_running,
                "interval_hours": self._get_interval(),
                "global_enabled": self._get_global_status()
            }
            
            if uid_ownership_col:
                # Count UIDs
                stats["total_uids"] = uid_ownership_col.count_documents({})
                stats["active_uids"] = uid_ownership_col.count_documents({"status": {"$ne": "removed"}})
                
                # Count pending submissions
                current_time = datetime.utcnow()
                stats["pending_submissions"] = uid_ownership_col.count_documents({
                    "$or": [
                        {"auto_submit_enabled": {"$ne": False}},
                        {"auto_submit_enabled": {"$exists": False}}
                    ],
                    "$or": [
                        {"next_auto_submit_time": {"$lte": current_time}},
                        {"next_auto_submit_time": {"$exists": False}},
                        {"last_auto_submit_time": {"$exists": False}}
                    ],
                    "status": {"$ne": "removed"}
                })
                
                # Get submission stats from logs
                if auto_submit_logs_col:
                    success_count = auto_submit_logs_col.count_documents({
                        "type": "auto_submit",
                        "success": True
                    })
                    failed_count = auto_submit_logs_col.count_documents({
                        "type": "auto_submit",
                        "success": False
                    })
                    stats["successful_submissions"] = success_count
                    stats["failed_submissions"] = failed_count
                    stats["total_processed"] = success_count + failed_count
            
            # Get scheduler status
            if self.scheduler:
                job = self.scheduler.get_job(self.job_id)
                if job and job.next_run_time:
                    stats["next_run_time"] = job.next_run_time.isoformat()
            
            return stats
            
        except Exception as e:
            print(f"Error getting stats: {e}")
            return {}
    
    def shutdown(self):
        """Shutdown the scheduler"""
        if self.scheduler:
            self.scheduler.shutdown()
            print("Auto Re-Add scheduler shutdown")

# Initialize Auto Re-Add Service
auto_re_add_service = AutoReAddService()

# ===== KEEP-ALIVE SELF-PING =====
def self_ping():
    """Keep the server alive on Render free tier"""
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
            print("[SELF-PING] SELF_URL not set — skipping ping.")

        time.sleep(8 * 60)

ping_thread = threading.Thread(target=self_ping, daemon=True)
ping_thread.start()

# ===== API HELPERS =====
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

    # Set initial auto-submit times
    current_time = datetime.utcnow()
    interval = auto_re_add_service._get_interval()
    
    uid_ownership_col.update_one(
        {"uid": uid},
        {"$set": {
            "uid": uid,
            "name": name,
            "days": days,
            "owner": owner,
            "expires_at": new_exp.isoformat(),
            "added_at": datetime.utcnow().isoformat(),
            "auto_submit_enabled": True,
            "last_auto_submit_time": current_time,
            "next_auto_submit_time": current_time + timedelta(hours=interval),
            "retry_count": 0,
            "status": "active"
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
            "username": username,
            "change": -1,
            "balance_after": current - 1,
            "reason": "UID added",
            "date": datetime.utcnow().isoformat()
        })
    return True

# ===== FETCHER HELPERS =====
def verify_fetcher(username, password):
    if fetchers_col is None:
        return False
    return fetchers_col.find_one({"username": username, "password": password}) is not None

def get_fetcher_permission_days(username):
    if fetchers_col is None:
        return 0
    doc = fetchers_col.find_one({"username": username})
    if not doc:
        return 0
    return int(doc.get("permission_days", 0))

# ===== SUB-ADMIN AUTH =====
def verify_subadmin(username, password):
    if subadmins_col is None:
        return False
    return subadmins_col.find_one({"username": username, "password": password}) is not None

# ============================================
# ROUTES
# ============================================

@app.route('/ping')
def ping():
    return jsonify({
        "status": "alive",
        "time": datetime.utcnow().isoformat(),
        "db": "connected" if mongo_client else "disconnected"
    }), 200

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
    uid = body.get("uid", "").strip()
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
    uid = body.get("uid", "").strip()
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

    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    note = body.get("note", "").strip()
    initial_credits = int(body.get("credits", 0))

    if not username or not password:
        return jsonify({"status": "error", "message": "username and password required"}), 400
    if subadmins_col.find_one({"username": username}):
        return jsonify({"status": "error", "message": "Username already exists"}), 409

    subadmins_col.insert_one({
        "username": username,
        "password": password,
        "note": note,
        "credits": initial_credits,
        "created_at": datetime.utcnow()
    })

    if initial_credits > 0 and credit_log_col is not None:
        credit_log_col.insert_one({
            "username": username,
            "change": initial_credits,
            "balance_after": initial_credits,
            "reason": "Initial credits on account creation",
            "date": datetime.utcnow().isoformat()
        })

    return jsonify({"status": "success", "message": f"Sub-admin '{username}' created", "credits": initial_credits}), 200

@app.route('/admin/give-credits', methods=['POST'])
def give_credits():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if subadmins_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500

    username = body.get("username", "").strip()
    amount = int(body.get("amount", 0))

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
            "username": username,
            "change": amount,
            "balance_after": new_balance,
            "reason": "Admin top-up",
            "date": datetime.utcnow().isoformat()
        })

    return jsonify({"status": "success", "message": f"Added {amount} credits to {username}", "new_credits": new_balance}), 200

@app.route('/admin/credit-log', methods=['GET'])
def get_credit_log():
    if request.args.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if credit_log_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500
    logs = list(credit_log_col.find({}, {"_id": 0}).sort("date", -1).limit(200))
    return jsonify({"status": "success", "logs": logs}), 200

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
    result = subadmins_col.delete_one({"username": username})
    if result.deleted_count == 0:
        return jsonify({"status": "error", "message": "Sub-admin not found"}), 404
    return jsonify({"status": "success", "message": f"Sub-admin '{username}' deleted"}), 200

# ===== FETCHER MANAGEMENT =====
@app.route('/admin/create-fetcher', methods=['POST'])
def create_fetcher():
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if fetchers_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500

    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    note = body.get("note", "").strip()
    permission_days = int(body.get("permission_days", 30))

    if not username or not password:
        return jsonify({"status": "error", "message": "username and password required"}), 400
    if permission_days < 1:
        return jsonify({"status": "error", "message": "permission_days must be at least 1"}), 400
    if fetchers_col.find_one({"username": username}):
        return jsonify({"status": "error", "message": "Username already exists"}), 409

    fetchers_col.insert_one({
        "username": username,
        "password": password,
        "note": note,
        "permission_days": permission_days,
        "created_at": datetime.utcnow()
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

    username = body.get("username", "").strip()
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
    result = fetchers_col.delete_one({"username": username})
    if result.deleted_count == 0:
        return jsonify({"status": "error", "message": "Fetcher not found"}), 404
    return jsonify({"status": "success", "message": f"Fetcher '{username}' deleted"}), 200

# ============================================
# AUTO RE-ADD ADMIN ROUTES
# ============================================

@app.route('/admin/auto-submit/stats', methods=['GET'])
def auto_submit_stats():
    """Get auto-submit statistics"""
    if request.args.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    
    stats = auto_re_add_service.get_stats()
    return jsonify({"status": "success", "stats": stats}), 200

@app.route('/admin/auto-submit/settings', methods=['GET', 'POST'])
def auto_submit_settings():
    """Get or update auto-submit settings"""
    if request.args.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    
    if request.method == 'GET':
        settings = {
            "enabled": auto_re_add_service._get_global_status(),
            "interval_hours": auto_re_add_service._get_interval(),
            "max_retry_attempts": MAX_RETRY_ATTEMPTS,
            "retry_delay": RETRY_DELAY
        }
        return jsonify({"status": "success", "settings": settings}), 200
    
    if request.method == 'POST':
        body = request.json or {}
        
        if 'enabled' in body:
            auto_re_add_service.set_global_status(body['enabled'])
        
        if 'interval_hours' in body:
            auto_re_add_service.update_interval(body['interval_hours'])
        
        return jsonify({"status": "success", "message": "Settings updated"}), 200

@app.route('/admin/auto-submit/force', methods=['POST'])
def auto_submit_force():
    """Force run auto-submit immediately"""
    if request.json and request.json.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    
    success = auto_re_add_service.force_run_now()
    if success:
        return jsonify({"status": "success", "message": "Auto-submit triggered"}), 200
    else:
        return jsonify({"status": "error", "message": "Failed to trigger auto-submit"}), 500

@app.route('/admin/auto-submit/toggle-uid', methods=['POST'])
def auto_submit_toggle_uid():
    """Enable or disable auto-submit for a specific UID"""
    body = request.json or {}
    if body.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    
    uid = body.get("uid", "").strip()
    enabled = body.get("enabled", True)
    
    if not uid:
        return jsonify({"status": "error", "message": "uid required"}), 400
    
    success = auto_re_add_service.toggle_uid_auto_submit(uid, enabled)
    if success:
        return jsonify({"status": "success", "message": f"Auto-submit {'enabled' if enabled else 'disabled'} for {uid}"}), 200
    else:
        return jsonify({"status": "error", "message": "Failed to update UID"}), 500

@app.route('/admin/auto-submit/logs', methods=['GET'])
def auto_submit_logs():
    """Get auto-submit logs"""
    if request.args.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    
    if auto_submit_logs_col is None:
        return jsonify({"status": "error", "message": "Database not connected"}), 500
    
    limit = int(request.args.get("limit", 100))
    logs = list(auto_submit_logs_col.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit))
    
    # Convert datetime objects to strings
    for log in logs:
        if log.get("timestamp"):
            log["timestamp"] = log["timestamp"].isoformat()
    
    return jsonify({"status": "success", "logs": logs}), 200

# ============================================
# SUB-ADMIN ROUTES
# ============================================

@app.route('/subadmin/login', methods=['POST'])
def subadmin_login():
    body = request.json or {}
    if verify_subadmin(body.get("username", ""), body.get("password", "")):
        return jsonify({"status": "success", "role": "sub_admin", "username": body["username"]}), 200
    return jsonify({"status": "error", "message": "Invalid credentials"}), 403

@app.route('/subadmin/credits', methods=['GET'])
def subadmin_credits():
    username = request.args.get("username", "")
    password = request.args.get("password", "")
    if not verify_subadmin(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    credits = get_subadmin_credits(username)
    return jsonify({"status": "success", "credits": credits, "username": username}), 200

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
        owned = set(doc["uid"] for doc in uid_ownership_col.find({"owner": username}, {"uid": 1}))
        my_uids = [u for u in all_uids if (u.get("uid") or u.get("id") or "") in owned]
    else:
        my_uids = all_uids

    return jsonify({"status": "success", "total": len(my_uids), "licenses": my_uids}), 200

@app.route('/subadmin/create', methods=['POST'])
def subadmin_create():
    body = request.json or {}
    username = body.get("username", "")
    password = body.get("password", "")
    if not verify_subadmin(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    current_credits = get_subadmin_credits(username)
    if current_credits < 1:
        return jsonify({"status": "error", "message": "❌ No credits! Contact Main Admin."}), 402

    uid = body.get("uid", "").strip()
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

    data, code = api_remove_uid(uid)
    if uid_ownership_col is not None:
        uid_ownership_col.delete_one({"uid": uid})
    if code == 200:
        return jsonify({"status": "success", "message": f"UID {uid} removed"}), 200
    return jsonify({"status": "error", "message": data.get("message", data.get("error", "API error"))}), code

@app.route('/subadmin/update', methods=['POST'])
def subadmin_update():
    body = request.json or {}
    username = body.get("username", "")
    password = body.get("password", "")
    if not verify_subadmin(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    uid = body.get("uid", "").strip()
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

# ============================================
# FETCHER ROUTES
# ============================================

@app.route('/fetcher/login', methods=['POST'])
def fetcher_login():
    body = request.json or {}
    if verify_fetcher(body.get("username", ""), body.get("password", "")):
        return jsonify({"status": "success", "role": "fetcher", "username": body["username"]}), 200
    return jsonify({"status": "error", "message": "Invalid credentials"}), 403

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
        owned = set(doc["uid"] for doc in uid_ownership_col.find({"owner": username}, {"uid": 1}))
        my_uids = [u for u in all_uids if (u.get("uid") or u.get("id") or "") in owned]
    else:
        my_uids = all_uids

    return jsonify({"status": "success", "total": len(my_uids), "licenses": my_uids}), 200

@app.route('/fetcher/create', methods=['POST'])
def fetcher_create():
    body = request.json or {}
    username = body.get("username", "")
    password = body.get("password", "")
    if not verify_fetcher(username, password):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    permission_days = get_fetcher_permission_days(username)
    if permission_days < 1:
        return jsonify({"status": "error", "message": "❌ No permission set! Contact Main Admin."}), 402

    uid = body.get("uid", "").strip()
    name = body.get("name", "Player").strip()
    if not uid:
        return jsonify({"status": "error", "message": "uid required"}), 400

    data, code = api_add_uid(uid, permission_days)
    if code in (200, 201):
        save_uid_meta(uid, name, permission_days, owner=username, extend=False)
        return jsonify({"status": "success", "message": f"UID added ({permission_days}d)", "data": data}), 200

    return jsonify({"status": "error", "message": data.get("message", data.get("error", "API error"))}), code

@app.route('/fetcher/revoke', methods=['POST'])
def fetcher_revoke():
    body = request.json or {}
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
    body = request.json or {}
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

# ===== DB STATUS =====
@app.route('/admin/db-status', methods=['GET'])
def db_status():
    if request.args.get("admin_key") != ADMIN_KEY:
        return jsonify({"status": "error", "message": "Invalid admin key"}), 403
    if subadmins_col is None:
        return jsonify({"status": "error", "message": "MongoDB NOT connected"}), 500
    return jsonify({"status": "success", "message": "MongoDB connected OK"}), 200

# ============================================
# STARTUP
# ============================================

# Initialize the auto re-add scheduler on startup
auto_re_add_service.init_scheduler()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8002))
    app.run(host='0.0.0.0', port=port, debug=False)
