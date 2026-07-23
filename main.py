import os
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import pandas as pd
import pdfplumber
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

PORT = int(os.environ.get("PORT", 8080))
TOKEN = os.environ.get("BOT_TOKEN")

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot ishlayapti!")

    def log_message(self, format, *args):
        return

def run_http_server():
    server = HTTPServer(('0.0.0.0', PORT), SimpleHTTPRequestHandler)
    server.serve_forever()

def process_ditat_pdf(pdf_path):
    data = []
    
    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join([p.extract_text() for p in pdf.pages if p.extract_text()])

    lines = full_text.split('\n')
    
    # 1. EARNINGS (FLAT, DETENTION, LAYOVER, MGAP, DriverAssist va b.)
    current_load_ref = ""
    in_earnings_section = False

    for i, line in enumerate(lines):
        line_str = line.strip()

        if 'Earnings' in line_str:
            in_earnings_section = True
            continue
        if 'Deductions' in line_str or 'Reimbursements' in line_str or 'Advances' in line_str:
            in_earnings_section = False

        if in_earnings_section:
            ref_match = re.search(r'\b(\d{5,10}|LD\d{5}|S\d{6,8})\b', line_str, re.IGNORECASE)
            if ref_match:
                current_load_ref = ref_match.group(1)

            # DriverAssist / Driver Assist
            driver_assist_match = re.search(
                r'^(DriverAssist|Driver\s+Assist)\s+(.*?)\s+(-?[\d\.]+)\s+\$([\d,]+\.\d{2})\s+\(?\$?\(?([\d,]+\.\d{2})\)?', 
                line_str, 
                re.IGNORECASE
            )
            if driver_assist_match:
                pay_type = driver_assist_match.group(1)
                desc = driver_assist_match.group(2).strip()
                pay_str = driver_assist_match.group(5).replace(',', '')
                pay_val = float(pay_str)
                
                if '(' in line_str or '-' in line_str:
                    pay_val = -abs(pay_val)

                ref_text = f"Load#: {current_load_ref}" if current_load_ref else "Load"
                description_text = f"{ref_text} | {pay_type} ({desc}) @ (${abs(pay_val):.2f})"

                data.append({
                    'CATEGORY': 'Driver payment',
                    'DESCRIPTION': description_text,
                    'AMOUNT': pay_val
                })
                continue

            # Boshqa to'lov turlari
            pay_match = re.search(
                r'^(FLAT|DETENTION|LAYOVER|MGAP|EMPTY\s*MILES|LOADED\s*MILES|MILEAGE|TONU|EXTRA\s+STOP|LUMPER)\s+(.*?)\s+([\d\.]+)\s+\$([\d,]+\.\d{2})\s+\$([\d,]+\.\d{2})', 
                line_str, 
                re.IGNORECASE
            )
            
            if pay_match:
                pay_type = pay_match.group(1).upper()
                desc = pay_match.group(2).strip()
                rate_val = pay_match.group(4).replace(',', '')
                pay_val = float(pay_match.group(5).replace(',', ''))

                ref_text = f"Load#: {current_load_ref}" if current_load_ref else "Load"
                
                if pay_type == 'FLAT':
                    description_text = f"{ref_text} Percentage: 88% of ${float(rate_val):.2f} @ ${pay_val:.2f}"
                else:
                    description_text = f"{ref_text} | {pay_type} ({desc}) @ ${pay_val:.2f}"

                data.append({
                    'CATEGORY': 'Load Expanse',
                    'DESCRIPTION': description_text,
                    'AMOUNT': pay_val
                })

    # 2. DEDUCTIONS, REIMBURSEMENTS, ADVANCES
    seen_deductions = set()
    for i, line in enumerate(lines):
        line_str = line.strip()
        
        # Admin Fee
        if 'Admin Fee' in line_str:
            amt_match = re.search(r'\(\$?([\d,]+\.\d{2})\)', line_str) or (re.search(r'\(\$?([\d,]+\.\d{2})\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1).replace(',', ''))
                key = f"admin_{val}_{i}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'Admin Fee', 'DESCRIPTION': f'Deduction | ADMINISTRATION FEE @ (${val:.2f})', 'AMOUNT': -abs(val)})

        # IFTA
        elif 'IFTA' in line_str:
            amt_match = re.search(r'\(\$?([\d,]+\.\d{2})\)', line_str) or (re.search(r'\(\$?([\d,]+\.\d{2})\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1).replace(',', ''))
                key = f"ifta_{val}_{i}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'Ifta', 'DESCRIPTION': f'Deduction | IFTA @ (${val:.2f})', 'AMOUNT': -abs(val)})

        # Parking
        elif 'PARKING' in line_str.upper():
            amt_match = re.search(r'\(\$?([\d,]+\.\d{2})\)', line_str) or (re.search(r'\(\$?([\d,]+\.\d{2})\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1).replace(',', ''))
                key = f"parking_{val}_{i}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'Driver loan Clearing', 'DESCRIPTION': f'Deduction | PARKING @ (${val:.2f})', 'AMOUNT': -abs(val)})

        # Trailer Rental
        elif 'TRAILER RENTAL' in line_str.upper() or 'TRAILERRENTAL' in line_str.upper():
            amt_match = re.search(r'\(\$?([\d,]+\.\d{2})\)', line_str) or (re.search(r'\(\$?([\d,]+\.\d{2})\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1).replace(',', ''))
                key = f"tr_rental_{val}_{i}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'Trailer Rental Revenue', 'DESCRIPTION': f'Deduction | TRAILER RENTAL @ (${val:.2f})', 'AMOUNT': -abs(val)})

        # Security Deposit
        elif 'SECURITY DEPOSIT' in line_str.upper():
            amt_match = re.search(r'\(\$?([\d,]+\.\d{2})\)', line_str) or (re.search(r'\(\$?([\d,]+\.\d{2})\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1).replace(',', ''))
                key = f"sec_dep_{val}_{i}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'Security Deposit Refundable', 'DESCRIPTION': f'Deduction | SECURITY DEPOSIT @ (${val:.2f})', 'AMOUNT': -abs(val)})

        # Reimbursements: Bonus
        elif 'BONUS' in line_str.upper():
            amt_match = re.search(r'\$([\d,]+\.\d{2})\s*$', line_str) or (re.search(r'\$([\d,]+\.\d{2})\s*$', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1).replace(',', ''))
                key = f"bonus_{val}_{i}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'No Violation Reward', 'DESCRIPTION': f'Reimbursement | BONUS @ ${val:.2f}', 'AMOUNT': abs(val)})

        # Reimbursements: Discount
        elif 'DISCOUNT' in line_str.upper():
            amt_match = re.search(r'\$([\d,]+\.\d{2})\s*$', line_str) or (re.search(r'\$([\d,]+\.\d{2})\s*$', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1).replace(',', ''))
                key = f"discount_{val}_{i}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'Fuel Discount', 'DESCRIPTION': f'Reimbursement | DISCOUNT @ ${val:.2f}', 'AMOUNT': abs(val)})

        # Cargo Insurance
        elif 'Cargo Insurance' in line_str:
            amt_match = re.search(r'\(\$?([\d,]+\.\d{2})\)', line_str) or (re.search(r'\(\$?([\d,]+\.\d{2})\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1).replace(',', ''))
                key = f"cargo_{val}_{i}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'Insurance refund', 'DESCRIPTION': f'Deduction | CARGO INSURANCE @ (${val:.2f})', 'AMOUNT': -abs(val)})

        # EFS
        elif 'EFS #' in line_str:
            amt_match = re.search(r'\(\$?([\d,]+\.\d{2})\)', line_str) or (re.search(r'\(\$?([\d,]+\.\d{2})\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1).replace(',', ''))
                key = f"efs_{val}_{i}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'Driver loan Clearing', 'DESCRIPTION': f'Deduction | MONEY CODE @ (${val:.2f})', 'AMOUNT': -abs(val)})

        # Short pay / Other
        elif 'SHORT PAY' in line_str.upper() or 'OTHER' in line_str.upper():
            amt_match = re.search(r'\(\$?([\d,]+\.\d{2})\)', line_str) or (re.search(r'\(\$?([\d,]+\.\d{2})\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1).replace(',', ''))
                key = f"other_{val}_{i}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    desc_label = 'SHORT PAY' if 'SHORT PAY' in line_str.upper() else 'OTHER'
                    data.append({'CATEGORY': 'Driver loan Clearing', 'DESCRIPTION': f'Deduction | {desc_label} @ (${val:.2f})', 'AMOUNT': -abs(val)})

        # Tolls
        elif 'Toll' in line_str or 'Tolls' in line_str:
            amt_match = re.search(r'\(\$?([\d,]+\.\d{2})\)', line_str) or (re.search(r'\(\$?([\d,]+\.\d{2})\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1).replace(',', ''))
                key = f"toll_{val}_{i}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'Driver loan Clearing', 'DESCRIPTION': f'Deduction | TOLLS @ (${val:.2f})', 'AMOUNT': -abs(val)})

        # OAI
        elif 'OAI' in line_str or 'Occupational accident' in line_str:
            amt_match = re.search(r'\(\$?([\d,]+\.\d{2})\)', line_str) or (re.search(r'\(\$?([\d,]+\.\d{2})\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1).replace(',', ''))
                key = f"oai_{val}_{i}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'Occupational Insurance Refund', 'DESCRIPTION': f'Deduction | OCCUPATIONAL ACCIDENT INSURANCE @ (${val:.2f})', 'AMOUNT': -abs(val)})

        # FEE / FUEL (TUGIRILGAN REGEX - Vergullik va har bir qator summasini to'g'ri oladi)
        elif 'FEE' in line_str.upper() or 'FUEL' in line_str.upper() or 'FUEL ADDITIVES' in line_str.upper() or 'CARRIER FEE' in line_str.upper():
            amt_match = re.search(r'\(\$?([\d,]+\.\d{2})\)', line_str) or (re.search(r'\(\$?([\d,]+\.\d{2})\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1).replace(',', ''))
                key = f"fuel_adv_{val}_{i}"
                if key not in seen_deductions and val > 0:
                    seen_deductions.add(key)
                    loc_match = re.search(r'([A-Za-z0-9\s,#\.-]+?)(?:FUEL|FEE)', line_str, re.IGNORECASE)
                    loc = loc_match.group(1).strip() if loc_match and len(loc_match.group(1).strip()) > 0 else "FUEL"
                    data.append({'CATEGORY': 'Prepaid Fuel', 'DESCRIPTION': f'Fuel | {loc} @ (${val:,.2f})', 'AMOUNT': -abs(val)})

    return pd.DataFrame(data)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Salom! PDF faylingizni yuboring, uni Excelga o'tkazib beraman.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.lower().endswith('.pdf'):
        await update.message.reply_text("Iltimos, faqat PDF formatidagi fayl yuboring!")
        return

    await update.message.reply_text("Fayl qabul qilindi, ishlanmoqda...")
    
    pdf_file = await context.bot.get_file(doc.file_id)
    pdf_path = f"temp_{doc.file_name}"
    await pdf_file.download_to_drive(pdf_path)
    
    excel_path = pdf_path.replace('.pdf', '.xlsx')

    try:
        df = process_ditat_pdf(pdf_path)
        
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='File', index=False)

        with open(excel_path, 'rb') as f:
            await update.message.reply_document(document=f, filename=f"Excel_{doc.file_name.replace('.pdf', '.xlsx')}")

    except Exception as e:
        await update.message.reply_text(f"Xatolik yuz berdi: {str(e)}")
    finally:
        if os.path.exists(pdf_path): 
            os.remove(pdf_path)
        if os.path.exists(excel_path): 
            os.remove(excel_path)

if __name__ == '__main__':
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    
    print("Bot va Port server ishga tushdi...")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.run_polling()
