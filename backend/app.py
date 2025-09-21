from pdf_parser import extract_pdf_text, parse_transactions
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from pathlib import Path
import os
from dotenv import load_dotenv
from collections import defaultdict
from datetime import datetime
import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('debug.log', mode='w'),  # 'w' mode overwrites the file each time
        logging.StreamHandler(sys.stdout)
    ]
)
# Set log level for specific modules
logging.getLogger('werkzeug').setLevel(logging.WARNING)  # Reduce Flask debug output

# Load environment variables from .env file
load_dotenv()

# Directories
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / 'frontend'
UPLOAD_DIR = BASE_DIR / 'uploads'
UPLOAD_DIR.mkdir(exist_ok=True)

# Allowed file types
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

# Helper functions for balance analysis
def calculate_daily_balances(transactions, start_date, end_date):
    """Calculate daily balances for MAB calculation."""
    from datetime import timedelta
    
    # Sort transactions by date
    sorted_trans = sorted(transactions, key=lambda x: datetime.strptime(x['date'], '%d %b %Y'))
    
    # Initialize daily balances dictionary
    daily_balances = {}
    current_balance = float(sorted_trans[0]['balance'])  # Start with first transaction's balance
    current_date = start_date
    
    # Initialize the first day's balance
    daily_balances[start_date.strftime('%Y-%m-%d')] = current_balance
    
    # Calculate balance for each day in the period
    while current_date <= end_date:
        date_str = current_date.strftime('%Y-%m-%d')
        
        # Find all transactions for this date
        days_transactions = [t for t in sorted_trans if 
                           datetime.strptime(t['date'], '%d %b %Y').date() == current_date.date()]
        
        if days_transactions:
            # Use the last transaction's balance for this day
            current_balance = float(days_transactions[-1]['balance'])
        
        daily_balances[date_str] = current_balance
        current_date += timedelta(days=1)
    
    return daily_balances

def calculate_monthly_statistics(transactions):
    """Calculate monthly balance statistics from transactions."""
    if not transactions:
        return {}
        
    monthly_stats = defaultdict(lambda: {
        'min_balance': float('inf'),
        'max_balance': float('-inf'),
        'avg_balance': 0.0,
        'days_maintained': 0,
        'total_balance': 0.0,
        'count': 0,
        'daily_balances': {}
    })
    
    # Get date range for all transactions
    dates = [datetime.strptime(t['date'], '%d %b %Y') for t in transactions]
    overall_start = min(dates)
    overall_end = max(dates)
    
    # Group transactions by month
    monthly_transactions = defaultdict(list)
    for trans in transactions:
        date = datetime.strptime(trans['date'], '%d %b %Y')
        month_key = f"{date.year}-{date.month:02d}"
        monthly_transactions[month_key].append(trans)
    
    # Calculate statistics for each month
    for month_key, month_trans in monthly_transactions.items():
        year = int(month_key.split('-')[0])
        month = int(month_key.split('-')[1])
        
        # Find start and end dates for this month
        month_dates = [datetime.strptime(t['date'], '%d %b %Y') for t in month_trans]
        month_start = min(month_dates)
        month_end = max(month_dates)
        
        # Calculate daily balances for this month
        daily_balances = calculate_daily_balances(month_trans, month_start, month_end)
        
        # Calculate statistics
        balances = list(daily_balances.values())
        stats = monthly_stats[month_key]
        stats['min_balance'] = min(balances)
        stats['max_balance'] = max(balances)
        stats['total_balance'] = sum(balances)
        stats['count'] = len(balances)  # Number of days
        stats['daily_balances'] = daily_balances  # Store daily balances for reference
    
    # Calculate averages and format results
    results = {}
    for month, stats in monthly_stats.items():
        if stats['count'] > 0:
            # Calculate true Monthly Average Balance (MAB)
            stats['avg_balance'] = stats['total_balance'] / stats['count']
            
            results[month] = {
                'min_balance': round(stats['min_balance'], 2),
                'max_balance': round(stats['max_balance'], 2),
                'avg_balance': round(stats['avg_balance'], 2),
                'days_maintained': stats['count'],
                'daily_balances': stats['daily_balances'],
                'mab_calculation': {
                    'sum_of_daily_balances': round(stats['total_balance'], 2),
                    'number_of_days': stats['count'],
                    'formula': 'MAB = Sum of daily balances / Number of days',
                    'calculation': f"MAB = ₹{round(stats['total_balance'], 2)} / {stats['count']} days = ₹{round(stats['avg_balance'], 2)}"
                }
            }
    
    return results

def analyze_balance_maintenance(transactions, target_balance):
    """Analyze balance maintenance against target amount."""
    if not transactions:
        return {
            'average_balance': 0,
            'maintenance_status': 'No transactions found',
            'recommendation': 'Unable to provide recommendation without transaction data'
        }
    
    # Calculate date range of statement
    dates = [datetime.strptime(t['date'], '%d %b %Y') for t in transactions]
    start_date = min(dates)
    end_date = max(dates)
    statement_period = {
        'start': start_date.strftime('%B %Y'),
        'end': end_date.strftime('%B %Y')
    }
    
    balances = [float(t['balance']) for t in transactions]
    avg_balance = sum(balances) / len(balances)
    min_balance = min(balances)
    max_balance = max(balances)
    
    # Calculate percentage of target maintained
    target_balance = float(target_balance) if target_balance else 0
    maintenance_percent = (avg_balance / target_balance * 100) if target_balance > 0 else 0
    
    # Determine status and recommendations
    if target_balance == 0:
        status = "No target balance specified"
        recommendation = "Set a target balance to receive maintenance recommendations"
    elif avg_balance >= target_balance:
        status = f"Target balance maintained ({maintenance_percent:.1f}% of target)"
        if avg_balance > target_balance * 1.5:
            excess = avg_balance - target_balance
            recommendation = (
                f"Your average balance of ₹{avg_balance:,.2f} exceeds the target by ₹{excess:,.2f}. "
                "Consider investing the excess funds while maintaining your target balance."
            )
        else:
            recommendation = (
                f"Great job! Your average balance of ₹{avg_balance:,.2f} is meeting the "
                f"target requirement of ₹{target_balance:,.2f}."
            )
    else:
        status = f"Below target ({maintenance_percent:.1f}% of target)"
        shortfall = target_balance - avg_balance
        monthly_deposit = shortfall / 3
        
        # Calculate the required end-of-month balance to maintain
        required_monthly_balance = max(target_balance, avg_balance + monthly_deposit)
        
        recommendation = (
            f"To reach your target balance of ₹{target_balance:,.2f}, "
            f"please maintain a minimum balance of ₹{required_monthly_balance:,.2f} "
            f"or deposit ₹{monthly_deposit:,.2f} monthly."
            f"This will help you build up to the required average balance of ₹{target_balance:,.2f}"
        )
    
    # Calculate shortfall or excess
    balance_difference = target_balance - avg_balance if target_balance > avg_balance else avg_balance - target_balance
    
    return {
        'average_balance': round(avg_balance, 2),
        'min_balance': round(min_balance, 2),
        'max_balance': round(max_balance, 2),
        'maintenance_status': status,
        'recommendation': recommendation,
        'target_balance': target_balance,
        'maintenance_percentage': round(maintenance_percent, 1),
        'statement_period': statement_period,
        'balance_difference': round(balance_difference, 2),
        'is_below_target': target_balance > avg_balance
    }

# Initialize Flask app
app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path='/')
# Configure CORS with specific settings
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})
app.config['UPLOAD_FOLDER'] = str(UPLOAD_DIR)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB
# Enable debug mode
app.debug = True

# Check file type
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Helper function for monthly balance analysis ---
def analyze_monthly_balance(transactions):
    """
    Expects transactions as a list of dicts with at least:
    [{'date': 'YYYY-MM-DD', 'balance': 1234}, ...]
    Returns a list of monthly summaries with min & avg balance
    """
    monthly_data = defaultdict(list)

    # Group balances by month-year
    for txn in transactions:
        try:
            txn_date = datetime.strptime(txn['date'], "%Y-%m-%d")
            month_key = txn_date.strftime("%b %Y")  # e.g., 'Jan 2025'
            monthly_data[month_key].append(txn['balance'])
        except Exception:
            continue  # skip if date/balance format is wrong

    # Prepare summary
    summary = []
    for month, balances in monthly_data.items():
        min_balance = min(balances)
        avg_balance = sum(balances) / len(balances)
        summary.append({
            "month": month,
            "min_balance": min_balance,
            "avg_balance": round(avg_balance, 2)
        })

    # Sort by month
    summary.sort(key=lambda x: datetime.strptime(x['month'], "%b %Y"))
    return summary

# Upload endpoint
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/upload', methods=['POST'])
def upload():
    logging.info("Received upload request")
    
    try:
        # Check if file exists in request
        if 'file' not in request.files:
            logging.error("No file in request")
            return jsonify({'status': 'error', 'message': 'No file found in request'}), 400

        file = request.files['file']
        target_balance = request.form.get('target_balance', '0')
        logging.info(f"Received file: {file.filename} with target balance: {target_balance}")

        # Validate file
        if file.filename == '':
            return jsonify({'status': 'error', 'message': 'No file selected'}), 400

        if not file.filename.lower().endswith('.pdf'):
            return jsonify({'status': 'error', 'message': 'Only PDF files are supported'}), 400

        if not allowed_file(file.filename):
            return jsonify({'status': 'error', 'message': 'Invalid file type'}), 400

        # Save file
        filename = secure_filename(file.filename)
        save_path = UPLOAD_DIR / filename
        file.save(save_path)
        
        logging.info(f"File saved successfully at {save_path}")

        # Process PDF and extract transactions
        try:
            logging.info(f"Starting PDF processing for {filename}")
            text = extract_pdf_text(str(save_path))
            logging.info(f"Extracted text length: {len(text)} characters")
            
            transactions = parse_transactions(text)
            logging.info(f"Parsed {len(transactions)} transactions")
            
            # Calculate summary statistics
            total_debits = sum(float(t['debit']) for t in transactions)
            total_credits = sum(float(t['credit']) for t in transactions)
            total_amount = total_credits - total_debits  # net change
            avg_transaction = total_amount / len(transactions) if transactions else 0

            response = {
                'status': 'success',
                'transactions': transactions,
                'summary': {
                    'total_transactions': len(transactions),
                    'total_amount': total_amount,
                    'average_transaction': avg_transaction
                }
            }
            return jsonify(response)
            
        except Exception as e:
            logging.error(f"Error processing file: {str(e)}")
            return jsonify({
                'status': 'error',
                'message': f'Error processing file: {str(e)}'
            }), 500
            
    except Exception as e:
        logging.error(f"Error processing upload: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to process file upload'}), 500
        try:
            if filename.lower().endswith('.pdf'):
                logging.info(f"Starting PDF processing for {filename}")
                text = extract_pdf_text(save_path)
                logging.info(f"Extracted text length: {len(text)} characters")
                transactions = parse_transactions(text)
                logging.info(f"Parsed {len(transactions)} transactions")
            else:
                logging.warning(f"Unsupported file type: {filename}")
                return jsonify({'status': 'error', 'message': 'Currently only PDF files are supported for transaction parsing'}), 400
        except Exception as e:
            logging.error(f"Error processing file: {str(e)}", exc_info=True)
            return jsonify({'status': 'error', 'message': f'Error processing file: {str(e)}'}), 500

        # --- Step 2: Analyze monthly balances ---
        monthly_summary = analyze_monthly_balance(transactions)

        # Prepare final result
        result = {
            'status': 'success',
            'filename': filename,
            'target_balance': target_balance,
            'processed_statements': 1,
            'transactions': transactions,
            'monthly_summary': monthly_summary,
            'message': 'Uploaded, parsed & analyzed successfully.'
        }
        return jsonify(result)

    return jsonify({'status': 'error', 'message': 'File type not allowed'}), 400

# Serve uploaded files
@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(str(UPLOAD_DIR), filename)

# Serve frontend
@app.route('/')
def index():
    return app.send_static_file('index.html')

# Run app
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
