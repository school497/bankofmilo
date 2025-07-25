from flask import Flask, request, jsonify, session, redirect, url_for, render_template
from functools import wraps
import requests
from requests.exceptions import RequestException, Timeout
import json

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change this in production

# Admin credentials (in production, use proper authentication)
ADMIN_USERNAME = 'milo'
ADMIN_PASSWORD = 'milo'

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return jsonify({'error': 'Admin authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    if not data or data.get('username') != ADMIN_USERNAME or data.get('password') != ADMIN_PASSWORD:
        return jsonify({'error': 'Invalid credentials'}), 401
    
    session['admin_logged_in'] = True
    return jsonify({'message': 'Login successful'})

@app.route('/admin/logout', methods=['POST'])
@admin_required
def admin_logout():
    session.pop('admin_logged_in', None)
    return jsonify({'message': 'Logout successful'})

def make_api_request(method, endpoint, **kwargs):
    try:
        # Add default timeout of 5 seconds
        kwargs.setdefault('timeout', 5)
        # Add admin credentials in headers
        kwargs.setdefault('headers', {})
        kwargs['headers'].update({
            'Authorization': f'{ADMIN_USERNAME}:{ADMIN_PASSWORD}',
            'Content-Type': 'application/json'
        })
        
        url = f'http://18.188.94.51:5789/api{endpoint}'
        print(f"DEBUG: Making {method.__name__.upper()} request to {url}")  # Debug log
        
        response = method(url, **kwargs)
        print(f"DEBUG: Response status: {response.status_code}")  # Debug log
        print(f"DEBUG: Response text: {response.text}")  # Debug log
        
        response.raise_for_status()
        
        try:
            return response.json(), response.status_code
        except json.JSONDecodeError as e:
            print(f"DEBUG: JSON decode error: {str(e)}")  # Debug log
            return {'error': 'Invalid response from API'}, 500
            
    except Timeout:
        return {'error': 'API request timed out'}, 504
    except RequestException as e:
        print(f"DEBUG: Request error: {str(e)}")  # Debug log
        return {'error': f'API request failed: {str(e)}'}, 502

@app.route('/admin/users', methods=['GET'])
@admin_required
def get_all_users():
    return make_api_request(requests.get, '/admin/accounts')

@app.route('/admin/user/<account_number>', methods=['GET'])
@admin_required
def get_user_details(account_number):
    return make_api_request(requests.get, f'/admin/accounts/{account_number}/details')

@app.route('/admin/atm-requests', methods=['GET'])
@admin_required
def get_atm_requests():
    return make_api_request(requests.get, '/admin/atm-requests')

@app.route('/admin/atm-requests/<int:request_id>/complete', methods=['POST'])
@admin_required
def complete_atm_request(request_id):
    return make_api_request(requests.post, f'/admin/atm-requests/{request_id}/complete')

@app.route('/admin/loans', methods=['GET'])
@admin_required
def get_loans():
    return make_api_request(requests.get, '/admin/loans')

@app.route('/admin/loans/<int:loan_id>/approve', methods=['POST'])
@admin_required
def approve_loan(loan_id):
    return make_api_request(requests.post, f'/admin/loans/{loan_id}/approve')

@app.route('/admin/loans/<int:loan_id>/deny', methods=['POST'])
@admin_required
def deny_loan(loan_id):
    return make_api_request(requests.post, f'/admin/loans/{loan_id}/deny')

@app.route('/admin/accounts/<account_number>/close', methods=['POST'])
@admin_required
def close_account(account_number):
    return make_api_request(requests.post, f'/admin/accounts/{account_number}/close')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)