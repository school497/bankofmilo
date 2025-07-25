from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# API configuration
API_BASE_URL = "http://18.188.94.51:5789"
DB_PATH = os.path.join(os.path.dirname(__file__), 'users.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            account_number TEXT PRIMARY KEY,
            username TEXT UNIQUE,
            password_hash TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/set_credentials', methods=['POST'])
def set_credentials():
    data = request.json
    account_number = data.get('account_number')
    username = data.get('username')
    password = data.get('password')
    if not all([account_number, username, password]):
        return jsonify({'error': 'Missing fields'}), 400
    password_hash = generate_password_hash(password)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('INSERT OR REPLACE INTO users (account_number, username, password_hash) VALUES (?, ?, ?)',
                  (account_number, username, password_hash))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Username already taken'}), 409
    conn.close()
    return jsonify({'success': True})

@app.route('/api/login_user', methods=['POST'])
def login_user():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT account_number, password_hash FROM users WHERE username=?', (username,))
    row = c.fetchone()
    conn.close()
    if row and check_password_hash(row[1], password):
        return jsonify({'account_number': row[0]})
    return jsonify({'error': 'Invalid username or password'}), 401

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=True)