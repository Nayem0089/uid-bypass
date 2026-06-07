from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
import os

app = Flask(__name__)

# ─── In-memory storage (no database needed) ───────────────────────────────────
users = {}  # uid -> {uid, name, expiry_date, status, created_at}

# Pre-loaded demo users
_demo = [
    ('10700059566', 'STREAM',  '2027-01-10'),
    ('11023982681', 'STREAM2', '2027-01-12'),
]
for _uid, _name, _exp in _demo:
    users[_uid] = {
        'uid': _uid, 'name': _name, 'expiry_date': _exp,
        'status': 'ACTIVE',
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

# ─── Helper ───────────────────────────────────────────────────────────────────
def calc_expiry(duration, custom_date=''):
    today = datetime.now().date()
    if duration == 'custom' and custom_date:
        return datetime.strptime(custom_date, '%Y-%m-%d').date()
    elif duration == '1_month':
        return today + timedelta(days=30)
    elif duration == '3_month':
        return today + timedelta(days=90)
    elif duration == 'lifetime':
        return today + timedelta(days=365 * 10)
    return None

def enrich(user):
    """Auto-set status based on expiry date."""
    u = dict(user)
    today = datetime.now().date()
    expiry = datetime.strptime(u['expiry_date'], '%Y-%m-%d').date()
    u['status'] = 'EXPIRED' if expiry < today else 'ACTIVE'
    return u

# ─── Routes ───────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/users', methods=['GET'])
def get_users():
    search = request.args.get('search', '').strip().lower()
    result = []
    for u in users.values():
        if search and search not in u['uid'].lower() and search not in u['name'].lower():
            continue
        result.append(enrich(u))

    result.sort(key=lambda x: x['uid'], reverse=True)
    active   = sum(1 for u in result if u['status'] == 'ACTIVE')
    expired  = sum(1 for u in result if u['status'] == 'EXPIRED')
    return jsonify({'users': result, 'stats': {'total': len(result), 'active': active, 'expired': expired}})

@app.route('/api/users', methods=['POST'])
def add_user():
    data = request.json or {}
    uid  = data.get('uid', '').strip()
    name = data.get('name', '').strip()
    if not uid or not name:
        return jsonify({'error': 'UID and Name are required'}), 400
    if uid in users:
        return jsonify({'error': 'UID already exists'}), 400

    try:
        expiry = calc_expiry(data.get('duration'), data.get('custom_date', ''))
    except ValueError:
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400

    if expiry is None:
        return jsonify({'error': 'Invalid duration selected'}), 400

    users[uid] = {
        'uid': uid, 'name': name,
        'expiry_date': expiry.strftime('%Y-%m-%d'),
        'status': 'ACTIVE',
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    return jsonify({'success': True, 'message': 'User added successfully'})

@app.route('/api/users/<uid>', methods=['DELETE'])
def remove_user(uid):
    if uid not in users:
        return jsonify({'error': 'User not found'}), 404
    del users[uid]
    return jsonify({'success': True, 'message': 'User removed successfully'})

@app.route('/api/users/<uid>/update', methods=['PUT'])
def update_user(uid):
    if uid not in users:
        return jsonify({'error': 'User not found'}), 404
    data = request.json or {}
    try:
        expiry = calc_expiry(data.get('duration'), data.get('custom_date', ''))
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400
    if expiry is None:
        return jsonify({'error': 'Invalid duration'}), 400

    users[uid]['expiry_date'] = expiry.strftime('%Y-%m-%d')
    users[uid]['status'] = 'ACTIVE'
    return jsonify({'success': True, 'message': 'User updated successfully'})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
