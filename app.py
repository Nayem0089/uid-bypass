from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
import sqlite3
import os

app = Flask(__name__)

# Database configuration
DATABASE = 'database.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """ডাটাবেস টেবিল তৈরি এবং প্রাথমিক ডাটা ইনসার্ট করার ফাংশন"""
    if not os.path.exists(DATABASE):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                expiry_date TEXT NOT NULL,
                status TEXT DEFAULT 'ACTIVE',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # ডেমো ইউজার ডাটা
        sample_users = [
            ('10700059566', 'STREAM', '2027-01-10', 'ACTIVE'),
            ('11023982681', 'STREAM2', '2027-01-12', 'ACTIVE')
        ]
        
        for user in sample_users:
            try:
                cursor.execute('''
                    INSERT INTO users (uid, name, expiry_date, status)
                    VALUES (?, ?, ?, ?)
                ''', user)
            except sqlite3.IntegrityError:
                pass 
        
        conn.commit()
        conn.close()

@app.route('/')
def index():
    """মূল ওয়েবসাইট পেজ লোড করার রুট"""
    return render_template('index.html')

@app.route('/api/users', methods=['GET'])
def get_users():
    """সব ইউজারদের তথ্য আনা এবং সার্চ করার API"""
    search = request.args.get('search', '').strip()
    conn = get_db()
    cursor = conn.cursor()
    
    if search:
        cursor.execute('''
            SELECT * FROM users WHERE uid LIKE ? OR name LIKE ?
            ORDER BY id DESC
        ''', (f'%{search}%', f'%{search}%'))
    else:
        cursor.execute('SELECT * FROM users ORDER BY id DESC')
    
    users = cursor.fetchall()
    conn.close()
    
    result = []
    active_count = 0
    expired_count = 0
    
    today = datetime.now().date()
    
    for user in users:
        user_dict = dict(user)
        expiry = datetime.strptime(user_dict['expiry_date'], '%Y-%m-%d').date()
        
        # এক্সপায়ারি ডেট পার হয়ে গেলে স্ট্যাটাস অটোমেটিক EXPIRED হবে
        if expiry < today:
            user_dict['status'] = 'EXPIRED'
            expired_count += 1
        elif user_dict['status'] == 'ACTIVE':
            active_count += 1
        else:
            expired_count += 1
            
        result.append(user_dict)
    
    return jsonify({
        'users': result,
        'stats': {
            'total': len(result),
            'active': active_count,
            'expired': expired_count
        }
    })

@app.route('/api/users', methods=['POST'])
def add_user():
    """নতুন ইউজার যুক্ত করার API"""
    data = request.json or {}
    uid = data.get('uid', '').strip()
    name = data.get('name', '').strip()
    duration = data.get('duration')  # '1_month', '3_month', 'lifetime', 'custom'
    custom_date = data.get('custom_date', '').strip()
    
    if not uid or not name:
        return jsonify({'error': 'UID and Name are required'}), 400
    
    today = datetime.now().date()
    
    # ডিউরেশন অনুযায়ী ডেট ক্যালকুলেশন
    if duration == 'custom' and custom_date:
        try:
            expiry_date = datetime.strptime(custom_date, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
    elif duration == '1_month':
        expiry_date = today + timedelta(days=30)
    elif duration == '3_month':
        expiry_date = today + timedelta(days=90)
    elif duration == 'lifetime':
        expiry_date = today + timedelta(days=365*10) # ১০ বছর
    else:
        return jsonify({'error': 'Invalid duration or date selected'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO users (uid, name, expiry_date, status)
            VALUES (?, ?, ?, 'ACTIVE')
        ''', (uid, name, expiry_date.strftime('%Y-%m-%d')))
        conn.commit()
        return jsonify({'success': True, 'message': 'User added successfully'})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'UID already exists'}), 400
    finally:
        conn.close()

@app.route('/api/users/<uid>', methods=['DELETE'])
def remove_user(uid):
    """ইউজার ডিলিট করার API"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM users WHERE uid = ?', (uid,))
    conn.commit()
    conn.close()
    
    if cursor.rowcount > 0:
        return jsonify({'success': True, 'message': 'User removed successfully'})
    else:
        return jsonify({'error': 'User not found'}), 404

@app.route('/api/users/<uid>/update', methods=['PUT'])
def update_user(uid):
    """ইউজারের মেয়াদ বা তথ্য আপডেট করার API"""
    data = request.json or {}
    duration = data.get('duration')
    custom_date = data.get('custom_date', '').strip()
    
    today = datetime.now().date()
    
    if duration == 'custom' and custom_date:
        try:
            expiry_date = datetime.strptime(custom_date, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format'}), 400
    elif duration == '1_month':
        expiry_date = today + timedelta(days=30)
    elif duration == '3_month':
        expiry_date = today + timedelta(days=90)
    elif duration == 'lifetime':
        expiry_date = today + timedelta(days=365*10)
    else:
        return jsonify({'error': 'Invalid duration'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users 
        SET expiry_date = ?, status = 'ACTIVE'
        WHERE uid = ?
    ''', (expiry_date.strftime('%Y-%m-%d'), uid))
    conn.commit()
    conn.close()
    
    if cursor.rowcount > 0:
        return jsonify({'success': True, 'message': 'User updated successfully'})
    else:
        return jsonify({'error': 'User not found'}), 404

if __name__ == '__main__':
    init_db()
    # Render বা হোস্টিং সার্ভার পোর্ট অটোমেটিক ডিটেক্ট করার জন্য
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)