from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime, timedelta
import random
import string
import threading
import time
from functools import wraps
import hashlib

app = Flask(__name__)

CORS(app)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bank_of_milo.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Models
class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_number = db.Column(db.String(16), unique=True, nullable=False)
    pin = db.Column(db.String(3), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    balance = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='active')  # active, on_hold, closed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_fee_date = db.Column(db.Date, default=datetime.utcnow().date())
    
    transactions = db.relationship('Transaction', backref='account', lazy=True)
    loans = db.relationship('Loan', backref='account', lazy=True)
    atm_requests = db.relationship('ATMRequest', backref='account', lazy=True)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)  # deposit, withdrawal, fee, loan_payment, loan_disbursement
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    balance_after = db.Column(db.Float, nullable=False)

class Loan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    reason = db.Column(db.String(500), nullable=False)
    preferred_date1 = db.Column(db.Date, nullable=False)
    preferred_date2 = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, approved, denied, completed
    approved_date1 = db.Column(db.Date)
    approved_date2 = db.Column(db.Date)
    first_payment_done = db.Column(db.Boolean, default=False)
    second_payment_done = db.Column(db.Boolean, default=False)
    applied_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime)

class ATMRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    request_type = db.Column(db.String(20), nullable=False)  # deposit, withdrawal
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, completed
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

# Helper Functions
def generate_account_number():
    """Generate a unique 16-digit account number"""
    while True:
        account_number = ''.join(random.choices(string.digits, k=16))
        if not Account.query.filter_by(account_number=account_number).first():
            return account_number

def generate_pin():
    """Generate a random 3-digit PIN"""
    return ''.join(random.choices(string.digits, k=3))

def add_transaction(account_id, transaction_type, amount, description=""):
    """Add a transaction record"""
    account = Account.query.get(account_id)
    transaction = Transaction(
        account_id=account_id,
        transaction_type=transaction_type,
        amount=amount,
        description=description,
        balance_after=account.balance
    )
    db.session.add(transaction)
    db.session.commit()

def check_account_status(account):
    """Check and update account status based on balance"""
    if account.balance < 0 and account.status == 'active':
        account.status = 'on_hold'
        db.session.commit()
    elif account.balance >= 0 and account.status == 'on_hold':
        account.status = 'active'
        db.session.commit()

def admin_required(f):
    """Decorator for admin authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check header auth first
        auth_header = request.headers.get('Authorization')
        if auth_header:
            auth = auth_header.split(':')
            if len(auth) == 2 and auth[0] == 'milo' and auth[1] == 'milo':
                return f(*args, **kwargs)
        
        # Fall back to JSON auth
        data = request.get_json()
        if not data or data.get('username') != 'milo' or data.get('password') != 'milo':
            return jsonify({'error': 'Admin authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function

# Background Tasks
def process_monthly_fees():
    """Process monthly fees for all accounts"""
    while True:
        try:
            with app.app_context():
                accounts = Account.query.filter_by(status='active').all()
                current_date = datetime.utcnow().date()
                
                for account in accounts:
                    # Check if a month has passed since last fee
                    if account.last_fee_date:
                        days_since_fee = (current_date - account.last_fee_date).days
                        if days_since_fee >= 30:  # Monthly fee
                            account.balance -= 5.0
                            account.last_fee_date = current_date
                            add_transaction(account.id, 'fee', -5.0, 'Monthly maintenance fee')
                            check_account_status(account)
                
                db.session.commit()
        except Exception as e:
            print(f"Error processing fees: {e}")
        
        time.sleep(86400)  # Check daily

def process_loan_payments():
    """Process automatic loan payments"""
    while True:
        try:
            with app.app_context():
                current_date = datetime.utcnow().date()
                loans = Loan.query.filter_by(status='approved').all()
                
                for loan in loans:
                    account = Account.query.get(loan.account_id)
                    
                    # First payment (50% of loan amount)
                    if (loan.approved_date1 and 
                        current_date >= loan.approved_date1 and 
                        not loan.first_payment_done):
                        
                        payment_amount = loan.amount * 0.5
                        if account.balance >= payment_amount:
                            account.balance -= payment_amount
                            loan.first_payment_done = True
                            add_transaction(account.id, 'loan_payment', -payment_amount, 
                                          f'First loan payment for loan #{loan.id}')
                            check_account_status(account)
                    
                    # Second payment (100% + 9.99% interest)
                    if (loan.approved_date2 and 
                        current_date >= loan.approved_date2 and 
                        not loan.second_payment_done and 
                        loan.first_payment_done):
                        
                        payment_amount = loan.amount * 1.0999  # 100% + 9.99% interest
                        if account.balance >= payment_amount:
                            account.balance -= payment_amount
                            loan.second_payment_done = True
                            loan.status = 'completed'
                            add_transaction(account.id, 'loan_payment', -payment_amount, 
                                          f'Final loan payment for loan #{loan.id}')
                            check_account_status(account)
                
                db.session.commit()
        except Exception as e:
            print(f"Error processing loan payments: {e}")
        
        time.sleep(86400)  # Check daily

# API Endpoints

# Account Management
@app.route('/api/accounts', methods=['POST'])
def create_account():
    """Create a new bank account"""
    data = request.get_json()
    
    if not data or not all(k in data for k in ('full_name', 'date_of_birth')):
        return jsonify({'error': 'Missing required fields'}), 400
    
    try:
        dob = datetime.strptime(data['date_of_birth'], '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
    
    account = Account(
        account_number=generate_account_number(),
        pin=generate_pin(),
        full_name=data['full_name'],
        date_of_birth=dob
    )
    
    db.session.add(account)
    db.session.commit()
    
    return jsonify({
        'message': 'Account created successfully',
        'account_number': account.account_number,
        'pin': account.pin
    }), 201

@app.route('/api/accounts/<account_number>/balance', methods=['POST'])
def get_balance_post(account_number):
    data = request.get_json()
    print(f"DEBUG: Received request for balance. account_number={account_number}, data={data}")  # Debug log
    if not data or 'pin' not in data:
        print("DEBUG: Missing PIN in request")  # Debug log
        return jsonify({'error': 'PIN required'}), 400

    # Ensure pin is compared as string
    pin = str(data['pin'])
    account = Account.query.filter_by(account_number=account_number, pin=pin).first()
    print(f"DEBUG: Account query result: {account}")  # Debug log
    if not account:
        print(f"DEBUG: No account found for account_number={account_number} and pin={pin}")  # Debug log
        return jsonify({'error': 'Invalid account number or PIN'}), 401

    print(f"DEBUG: Returning balance for account_number={account.account_number}")  # Debug log
    return jsonify({
        'account_number': account.account_number,
        'balance': account.balance,
        'status': account.status
    })

@app.route('/api/accounts/<account_number>/history', methods=['GET', 'POST'])  # Add POST method
def get_account_history(account_number):
    data = request.get_json()
    if not data or 'pin' not in data:
        return jsonify({'error': 'PIN required'}), 400
    
    account = Account.query.filter_by(account_number=account_number, pin=data['pin']).first()
    if not account:
        return jsonify({'error': 'Invalid account number or PIN'}), 401
    
    transactions = Transaction.query.filter_by(account_id=account.id).order_by(Transaction.timestamp.desc()).all()
    
    history = []
    for transaction in transactions:
        history.append({
            'id': transaction.id,
            'type': transaction.transaction_type,
            'amount': transaction.amount,
            'description': transaction.description,
            'timestamp': transaction.timestamp.isoformat(),
            'balance_after': transaction.balance_after
        })
    
    return jsonify({
        'account_number': account.account_number,
        'history': history
    })

# Loan Management
@app.route('/api/loans', methods=['POST'])
def apply_for_loan():
    """Apply for a loan"""
    data = request.get_json()
    
    required_fields = ['account_number', 'pin', 'amount', 'reason', 'preferred_date1', 'preferred_date2']
    if not data or not all(k in data for k in required_fields):
        return jsonify({'error': 'Missing required fields'}), 400
    
    account = Account.query.filter_by(account_number=data['account_number'], pin=data['pin']).first()
    if not account:
        return jsonify({'error': 'Invalid account number or PIN'}), 401
    
    if account.status != 'active':
        return jsonify({'error': 'Account is not active'}), 400
    
    try:
        date1 = datetime.strptime(data['preferred_date1'], '%Y-%m-%d').date()
        date2 = datetime.strptime(data['preferred_date2'], '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
    
    loan = Loan(
        account_id=account.id,
        amount=data['amount'],
        reason=data['reason'],
        preferred_date1=date1,
        preferred_date2=date2
    )
    
    db.session.add(loan)
    db.session.commit()
    
    return jsonify({
        'message': 'Loan application submitted successfully',
        'loan_id': loan.id,
        'status': loan.status
    }), 201

@app.route('/api/accounts/<account_number>/loans', methods=['GET', 'POST'])
def get_user_loans(account_number):
    data = request.get_json()
    if not data or 'pin' not in data:
        return jsonify({'error': 'PIN required'}), 400

    account = Account.query.filter_by(account_number=account_number, pin=data['pin']).first()
    if not account:
        return jsonify({'error': 'Invalid account number or PIN'}), 401

    loans = Loan.query.filter_by(account_id=account.id).order_by(Loan.applied_at.desc()).all()

    loan_list = []
    for loan in loans:
        loan_list.append({
            'id': loan.id,
            'amount': loan.amount,
            'reason': loan.reason,
            'status': loan.status,
            'preferred_date1': loan.preferred_date1.isoformat() if loan.preferred_date1 else None,
            'preferred_date2': loan.preferred_date2.isoformat() if loan.preferred_date2 else None,
            'approved_date1': loan.approved_date1.isoformat() if loan.approved_date1 else None,
            'approved_date2': loan.approved_date2.isoformat() if loan.approved_date2 else None,
            'first_payment_done': loan.first_payment_done,
            'second_payment_done': loan.second_payment_done,
            'applied_at': loan.applied_at.isoformat()
        })

    return jsonify({'loans': loan_list})

# ATM System
@app.route('/api/atm/auth', methods=['POST'])
def atm_authenticate():
    """Authenticate user for ATM access"""
    data = request.get_json()
    
    if not data or not all(k in data for k in ('account_number', 'pin')):
        return jsonify({'error': 'Missing account number or PIN'}), 400
    
    # Ensure both values are strings for comparison
    account_number = str(data['account_number'])
    pin = str(data['pin'])
    
    print(f"DEBUG: Authenticating account={account_number}, pin={pin}")  # Debug log
    
    account = Account.query.filter_by(account_number=account_number, pin=pin).first()
    if not account:
        print("DEBUG: Authentication failed - no matching account")  # Debug log
        return jsonify({'error': 'Invalid account number or PIN'}), 401
    
    print(f"DEBUG: Authentication successful for account {account.account_number}")  # Debug log
    return jsonify({
        'message': 'Authentication successful',
        'account_number': account.account_number,
        'balance': account.balance,
        'status': account.status
    })

@app.route('/api/atm/deposit', methods=['POST'])
def atm_deposit():
    """Request ATM deposit"""
    data = request.get_json()
    
    required_fields = ['account_number', 'pin', 'amount']
    if not data or not all(k in data for k in required_fields):
        return jsonify({'error': 'Missing required fields'}), 400
    
    account = Account.query.filter_by(account_number=data['account_number'], pin=data['pin']).first()
    if not account:
        return jsonify({'error': 'Invalid account number or PIN'}), 401
    
    if data['amount'] <= 0:
        return jsonify({'error': 'Amount must be positive'}), 400
    
    atm_request = ATMRequest(
        account_id=account.id,
        request_type='deposit',
        amount=data['amount']
    )
    
    db.session.add(atm_request)
    db.session.commit()
    
    return jsonify({
        'message': 'Deposit request submitted successfully',
        'request_id': atm_request.id,
        'status': atm_request.status
    }), 201

@app.route('/api/atm/withdraw', methods=['POST'])
def atm_withdraw():
    """Request ATM withdrawal"""
    data = request.get_json()
    
    required_fields = ['account_number', 'pin', 'amount']
    if not data or not all(k in data for k in required_fields):
        return jsonify({'error': 'Missing required fields'}), 400
    
    account = Account.query.filter_by(account_number=data['account_number'], pin=data['pin']).first()
    if not account:
        return jsonify({'error': 'Invalid account number or PIN'}), 401
    
    if account.status != 'active':
        return jsonify({'error': 'Account is on hold. Cannot withdraw funds.'}), 400
    
    if data['amount'] <= 0:
        return jsonify({'error': 'Amount must be positive'}), 400
    
    if data['amount'] > account.balance:
        return jsonify({'error': 'Insufficient funds'}), 400
    
    atm_request = ATMRequest(
        account_id=account.id,
        request_type='withdrawal',
        amount=data['amount']
    )
    
    db.session.add(atm_request)
    db.session.commit()
    
    return jsonify({
        'message': 'Withdrawal request submitted successfully',
        'request_id': atm_request.id,
        'status': atm_request.status
    }), 201

# Admin Endpoints
@app.route('/api/admin/accounts', methods=['GET', 'POST'])
@admin_required  # Use the updated decorator
def admin_get_all_accounts():
    """Get all accounts (admin only)"""
    accounts = Account.query.all()
    account_list = []
    
    for account in accounts:
        account_list.append({
            'id': account.id,
            'account_number': account.account_number,
            'full_name': account.full_name,
            'date_of_birth': account.date_of_birth.isoformat(),
            'balance': account.balance,
            'status': account.status,
            'created_at': account.created_at.isoformat()
        })
    
    return jsonify({'accounts': account_list})

@app.route('/api/admin/accounts/<account_number>/close', methods=['POST'])
@admin_required
def admin_close_account(account_number):
    """Close an account (admin only)"""
    account = Account.query.filter_by(account_number=account_number).first()
    if not account:
        return jsonify({'error': 'Account not found'}), 404
    
    account.status = 'closed'
    db.session.commit()
    
    return jsonify({'message': 'Account closed successfully'})

@app.route('/api/admin/accounts/<account_number>/details', methods=['GET', 'POST'])
@admin_required
def admin_get_account_details(account_number):
    """Get detailed account information (admin only)"""
    account = Account.query.filter_by(account_number=account_number).first()
    if not account:
        return jsonify({'error': 'Account not found'}), 404
    
    # Get transactions
    transactions = Transaction.query.filter_by(account_id=account.id).order_by(Transaction.timestamp.desc()).all()
    transaction_list = []
    for transaction in transactions:
        transaction_list.append({
            'id': transaction.id,
            'type': transaction.transaction_type,
            'amount': transaction.amount,
            'description': transaction.description,
            'timestamp': transaction.timestamp.isoformat(),
            'balance_after': transaction.balance_after
        })
    
    # Get loans
    loans = Loan.query.filter_by(account_id=account.id).order_by(Loan.applied_at.desc()).all()
    loan_list = []
    for loan in loans:
        loan_list.append({
            'id': loan.id,
            'amount': loan.amount,
            'reason': loan.reason,
            'status': loan.status,
            'preferred_date1': loan.preferred_date1.isoformat() if loan.preferred_date1 else None,
            'preferred_date2': loan.preferred_date2.isoformat() if loan.preferred_date2 else None,
            'approved_date1': loan.approved_date1.isoformat() if loan.approved_date1 else None,
            'approved_date2': loan.approved_date2.isoformat() if loan.approved_date2 else None,
            'first_payment_done': loan.first_payment_done,
            'second_payment_done': loan.second_payment_done,
            'applied_at': loan.applied_at.isoformat()
        })
    
    return jsonify({
        'account': {
            'id': account.id,
            'account_number': account.account_number,
            'full_name': account.full_name,
            'date_of_birth': account.date_of_birth.isoformat(),
            'balance': account.balance,
            'status': account.status,
            'created_at': account.created_at.isoformat()
        },
        'transactions': transaction_list,
        'loans': loan_list
    })

@app.route('/api/admin/loans', methods=['GET', 'POST'])
@admin_required
def admin_get_all_loans():
    """Get all loan applications (admin only)"""
    loans = Loan.query.order_by(Loan.applied_at.desc()).all()
    loan_list = []
    
    for loan in loans:
        account = Account.query.get(loan.account_id)
        loan_list.append({
            'id': loan.id,
            'account_number': account.account_number,
            'full_name': account.full_name,
            'amount': loan.amount,
            'reason': loan.reason,
            'status': loan.status,
            'preferred_date1': loan.preferred_date1.isoformat() if loan.preferred_date1 else None,
            'preferred_date2': loan.preferred_date2.isoformat() if loan.preferred_date2 else None,
            'approved_date1': loan.approved_date1.isoformat() if loan.approved_date1 else None,
            'approved_date2': loan.approved_date2.isoformat() if loan.approved_date2 else None,
            'first_payment_done': loan.first_payment_done,
            'second_payment_done': loan.second_payment_done,
            'applied_at': loan.applied_at.isoformat()
        })
    
    return jsonify({'loans': loan_list})

@app.route('/api/admin/loans/<int:loan_id>/approve', methods=['POST'])
def admin_approve_loan(loan_id):
    """Approve a loan (admin only)"""
    data = request.get_json()
    if not data or data.get('username') != 'milo' or data.get('password') != 'milo':
        return jsonify({'error': 'Admin authentication required'}), 401
    
    loan = Loan.query.get(loan_id)
    if not loan:
        return jsonify({'error': 'Loan not found'}), 404
    
    if loan.status != 'pending':
        return jsonify({'error': 'Loan is not pending'}), 400
    
    # Use preferred dates or custom dates if provided
    approved_date1 = loan.preferred_date1
    approved_date2 = loan.preferred_date2
    
    if 'approved_date1' in data:
        try:
            approved_date1 = datetime.strptime(data['approved_date1'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid approved_date1 format'}), 400
    
    if 'approved_date2' in data:
        try:
            approved_date2 = datetime.strptime(data['approved_date2'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid approved_date2 format'}), 400
    
    loan.status = 'approved'
    loan.approved_date1 = approved_date1
    loan.approved_date2 = approved_date2
    loan.approved_at = datetime.utcnow()
    
    # Add loan amount to account balance
    account = Account.query.get(loan.account_id)
    account.balance += loan.amount
    
    # Record transaction
    add_transaction(account.id, 'loan_disbursement', loan.amount, 
                   f'Loan disbursement for loan #{loan.id}')
    
    db.session.commit()
    
    return jsonify({'message': 'Loan approved successfully'})

@app.route('/api/admin/loans/<int:loan_id>/deny', methods=['POST'])
def admin_deny_loan(loan_id):
    """Deny a loan (admin only)"""
    data = request.get_json()
    if not data or data.get('username') != 'milo' or data.get('password') != 'milo':
        return jsonify({'error': 'Admin authentication required'}), 401
    
    loan = Loan.query.get(loan_id)
    if not loan:
        return jsonify({'error': 'Loan not found'}), 404
    
    if loan.status != 'pending':
        return jsonify({'error': 'Loan is not pending'}), 400
    
    loan.status = 'denied'
    db.session.commit()
    
    return jsonify({'message': 'Loan denied successfully'})

@app.route('/api/admin/atm-requests', methods=['GET', 'POST'])
@admin_required
def admin_get_atm_requests():
    """Get all ATM requests (admin only)"""
    requests = ATMRequest.query.order_by(ATMRequest.requested_at.desc()).all()
    request_list = []
    
    for req in requests:
        account = Account.query.get(req.account_id)
        request_list.append({
            'id': req.id,
            'account_number': account.account_number,
            'full_name': account.full_name,
            'type': req.request_type,
            'amount': req.amount,
            'status': req.status,
            'requested_at': req.requested_at.isoformat(),
            'completed_at': req.completed_at.isoformat() if req.completed_at else None
        })
    
    return jsonify({'requests': request_list})

@app.route('/api/admin/atm-requests/<int:request_id>/complete', methods=['POST'])
@admin_required  # Add this decorator
def admin_complete_atm_request(request_id):
    """Mark ATM request as completed (admin only)"""
    atm_request = ATMRequest.query.get(request_id)
    if not atm_request:
        return jsonify({'error': 'ATM request not found'}), 404
    
    if atm_request.status != 'pending':
        return jsonify({'error': 'ATM request is not pending'}), 400
    
    account = Account.query.get(atm_request.account_id)
    
    # Process the transaction
    if atm_request.request_type == 'deposit':
        account.balance += atm_request.amount
        add_transaction(account.id, 'deposit', atm_request.amount, 'ATM deposit')
    elif atm_request.request_type == 'withdrawal':
        account.balance -= atm_request.amount
        add_transaction(account.id, 'withdrawal', -atm_request.amount, 'ATM withdrawal')
    
    atm_request.status = 'completed'
    atm_request.completed_at = datetime.utcnow()
    
    # Check account status after transaction
    check_account_status(account)
    
    db.session.commit()
    
    return jsonify({'message': 'ATM request completed successfully'})

@app.route('/api/debug/accounts', methods=['GET'])
def debug_list_accounts():
    accounts = Account.query.all()
    return jsonify([
        {
            'account_number': a.account_number,
            'pin': a.pin,
            'full_name': a.full_name,
            'status': a.status,
            'balance': a.balance
        }
        for a in accounts
    ])

@app.route('/api/accounts/<account_number>/exists', methods=['GET'])
def check_account_exists(account_number):
    """Check if an account exists"""
    account = Account.query.filter_by(account_number=account_number).first()
    if account:
        return jsonify({'exists': True, 'status': account.status}), 200
    return jsonify({'exists': False}), 404

init_done = False

@app.before_request
def create_tables_once():
    global init_done
    if not init_done:
        db.create_all()
        # Start background tasks
        fee_thread = threading.Thread(target=process_monthly_fees, daemon=True)
        fee_thread.start()
        loan_thread = threading.Thread(target=process_loan_payments, daemon=True)
        loan_thread.start()
        init_done = True

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5789, debug=True)