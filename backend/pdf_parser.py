import pdfplumber
import re
import os
from datetime import datetime

def extract_pdf_text(pdf_path):
    """Extract all text from a PDF file."""
    print(f"\n{'='*50}")
    print(f"STARTING PDF EXTRACTION")
    print(f"File path: {pdf_path}")
    print(f"File exists: {os.path.exists(pdf_path)}")
    file_size = os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 'N/A'
    print(f"File size: {file_size} bytes")
    
    # List all files in uploads directory
    upload_dir = os.path.dirname(pdf_path)
    print(f"\nContents of upload directory ({upload_dir}):")
    for f in os.listdir(upload_dir):
        f_path = os.path.join(upload_dir, f)
        f_size = os.path.getsize(f_path)
        print(f"- {f} (Size: {f_size} bytes)")
    
    print(f"{'='*50}\n")
    
    full_text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            print(f"Successfully opened PDF with {len(pdf.pages)} pages")
            print("\nPDF Document Information:")
            print(f"Number of pages: {len(pdf.pages)}")
            if hasattr(pdf, 'metadata') and pdf.metadata:
                print("Metadata:")
                for key, value in pdf.metadata.items():
                    print(f"  {key}: {value}")
            else:
                print("No metadata available")
            for i, page in enumerate(pdf.pages):
                print(f"Processing page {i+1}")
                # Try to extract tables first
                tables = page.extract_tables()
                if tables:
                    print(f"\nFound {len(tables)} tables on page {i+1}")
                    for table_idx, table in enumerate(tables):
                        print(f"\nTable {table_idx + 1} on page {i+1}:")
                        print(f"Number of rows: {len(table)}")
                        
                        # Print table headers (first row) to help identify transaction tables
                        if table and len(table) > 0:
                            print("\nTable Headers:")
                            headers = [str(h) if h is not None else "" for h in table[0]]
                            print(" | ".join(headers))
                            
                        # Process each row
                        for row_idx, row in enumerate(table):
                            # Convert all items to strings and join with tabs
                            row_text = "\t".join(str(item) if item is not None else "" for item in row)
                            # Only print first 5 and last 5 rows to avoid flooding the logs
                            if row_idx < 5 or row_idx >= len(table) - 5:
                                print(f"Row {row_idx}: {row_text}")
                            elif row_idx == 5:
                                print("... [rows omitted for brevity] ...")
                            full_text += row_text + "\n"
                
                # Also get regular text
                text = page.extract_text()
                if text:
                    print(f"Extracted {len(text)} characters of regular text from page {i+1}")
                    full_text += text + "\n"
                else:
                    print(f"No regular text found on page {i+1}")
                
                # Print a sample of what we found
                print(f"Sample text from page {i+1}:")
                print(full_text.split('\n')[-5:] if full_text else "No text found")
    except Exception as e:
        print(f"Error extracting PDF text: {str(e)}")
        raise
    
    print(f"Finished extracting text, total {len(full_text)} characters")
    print("Sample of extracted text:")
    print("\n".join(full_text.split('\n')[:10]))  # Print first 10 lines
    return full_text

def parse_transactions(text):
    """Convert extracted PDF text into structured transaction rows."""
    print("Starting transaction parsing")
    print(f"Input text length: {len(text)}")
    print("First few lines of text:")
    for i, line in enumerate(text.split('\n')[:5]):
        print(f"Line {i+1}: {line}")
    
    transactions = []
    lines = text.split("\n")
    print(f"Found {len(lines)} lines to process")
    
    # SBI specific date format (e.g., "17 Sep 2024")
    date_pattern = r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})"
    # Amount patterns to match numbers with commas and decimals
    amount_pattern = r"(?:^|\s)([\d,]+\.\d{2})(?:\s|$)"  # Matches amounts like "1,234.56" with word boundaries
    
    current_row = []
    inside_table = False
    header_found = False
    
    for line in lines:
        # Check for table header
        if not header_found and all(x in line for x in ["Txn Date", "Date", "Description"]):
            header_found = True
            continue
        
        if not header_found:
            continue
            
        # Skip empty lines and header repetitions
        if not line.strip() or "Txn Date" in line:
            continue
        
        # Look for date in the line
        date_match = re.search(date_pattern, line)
        if date_match:
            # Process previous transaction if exists
            if current_row:
                debit = 0
                credit = 0
                balance = 0
                
                # Join all lines of the transaction
                full_text = " ".join(current_row)
                print(f"Processing transaction text: {full_text}")
                
                # Find all amounts
                amounts = re.findall(amount_pattern, full_text)
                amounts = [float(a.replace(",", "")) for a in amounts if a]
                print(f"Found amounts: {amounts}")
                
                if amounts:
                    # Last amount is always balance in SBI format
                    balance = amounts[-1]
                    
                    # Check the remaining amounts
                    if len(amounts) > 1:
                        # Look at transaction description to determine debit/credit
                        is_debit = any(x in full_text.lower() for x in ["debit", "transfer to", "paid to"])
                        transaction_amount = amounts[-2]  # Amount before balance
                        
                        if is_debit:
                            debit = transaction_amount
                        else:
                            credit = transaction_amount
                
                # Get the full date from matched pattern
                date_str = date_match.group(1)
                
                transaction = {
                    "date": date_str,
                    "debit": debit,
                    "credit": credit,
                    "balance": balance,
                    "description": full_text.split("\n")[0]  # Use first line as description
                }
                print(f"Parsed transaction: {transaction}")
                transactions.append(transaction)
            
            # Start new transaction
            current_row = [line]
            inside_table = True
        elif inside_table and line.strip():
            # Continue collecting lines for current transaction
            current_row.append(line)
    
    # Process last transaction if any
    if current_row:
        debit = 0
        credit = 0
        balance = 0
        
        full_text = " ".join(current_row)
        amounts = re.findall(amount_pattern, full_text)
        amounts = [float(a.replace(",", "")) for a in amounts if a]
        
        if amounts:
            balance = amounts[-1]
            if len(amounts) > 1:
                is_debit = any(x in full_text.lower() for x in ["debit", "transfer to", "paid to"])
                transaction_amount = amounts[-2]
                
                if is_debit:
                    debit = transaction_amount
                else:
                    credit = transaction_amount
        
        # Get the date from the last transaction
        date_match = re.search(date_pattern, full_text)
        if date_match:
            date_str = date_match.group(1)
            
            transaction = {
                "date": date_str,
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "amount": -debit if debit > 0 else credit,  # negative for debits, positive for credits
                "balance": balance,
                "amount": -debit if debit > 0 else credit,  # negative for debits, positive for credits
                "description": full_text.split("\n")[0]  # Use first line as description
            }
            print(f"Parsed transaction: {transaction}")
            transactions.append(transaction)
    
    print(f"Total transactions found: {len(transactions)}")
    if transactions:
        print("Sample transactions:")
        print("First:", transactions[0])
        print("Middle:", transactions[len(transactions)//2])
        print("Last:", transactions[-1])
    
    return transactions
