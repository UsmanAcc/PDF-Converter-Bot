import os
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import pandas as pd
import pdfplumber
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Render taqdim etadigan port (aks holda 8080)
PORT = int(os.environ.get("PORT", 8080))
TOKEN = os.environ.get("BOT_TOKEN")

# Render port scan xatosini oldini olish uchun HTTP Server
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot ishlayapti!")

    def log_message(self, format, *args):
        return  # Konsolni ortiqcha loglar bilan to'ldirmaslik uchun

def run_http_server():
    server = HTTPServer(('0.0.0.0', PORT), SimpleHTTPRequestHandler)
    server.serve_forever()

def process_ditat_pdf(pdf_path):
    data = []
    
    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join([p.extract_text() for p in pdf.pages if p.extract_text()])

    # 1. LOADLAR (Earnings)
    load_matches = re.findall(
        r'(4\d{5}|LD\d{5})[\s\S]*?Contracted flat amount[\s\S]*?([\d\.]+)[\s\S]*?\$([\d,]+\.\d{2})[\s\S]*?\$([\d,]+\.\d{2})',
        full_text
    )
    for ref, rate, gross, pay in load_matches:
        g_num = float(gross.replace(',', ''))
        p_num = float(pay.replace(',', ''))
        data.append({
            'CATEGORY': 'Load Expanse',
            'DESCRIPTION': f"Load#: {ref} Percentage: 88% of ${g_num:.2f} @ ${p_num:.2f}",
            'AMOUNT': p_num
        })

    seen_deductions = set()
    lines = full_text.split('\n')
    for i, line in enumerate(lines):
        line_str = line.strip()
        
        # Checking Admin Fee
        if 'Admin Fee' in line_str:
            amt_match = re.search(r'\(\$?([\d\.]+)\)', line_str) or (re.search(r'\(\$?([\d\.]+)\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1))
                key = f"admin_{val}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'Admin Fee', 'DESCRIPTION': f'Deduction | ADMINISTRATION FEE @ (${val:.2f})', 'AMOUNT': -abs(val)})

        # Checking IFTA
        elif 'IFTA' in line_str:
            amt_match = re.search(r'\(\$?([\d\.]+)\)', line_str) or (re.search(r'\(\$?([\d\.]+)\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1))
                key = f"ifta_{val}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'Ifta', 'DESCRIPTION': f'Deduction | IFTA @ (${val:.2f})', 'AMOUNT': -abs(val)})

        # Checking Security Deposit
        elif 'SECURITY DEPOSIT' in line_str.upper():
            amt_match = re.search(r'\(\$?([\d\.]+)\)', line_str) or (re.search(r'\(\$?([\d\.]+)\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1))
                key = f"sec_dep_{val}_{i}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'Security Deposit Refundable', 'DESCRIPTION': f'Deduction | SECURITY DEPOSIT @ (${val:.2f})', 'AMOUNT': -abs(val)})

        # Checking Reimbursements: Bonus
        elif 'BONUS' in line_str.upper():
            amt_match = re.search(r'\$?([\d\.]+)', line_str) or (re.search(r'\$?([\d\.]+)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1))
                key = f"bonus_{val}_{i}"
                if key not in seen_deductions and val > 0:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'No Violation Reward', 'DESCRIPTION': f'Reimbursement | BONUS @ ${val:.2f}', 'AMOUNT': abs(val)})

        # Checking Cargo Insurance
        elif 'Cargo Insurance' in line_str:
            amt_match = re.search(r'\(\$?([\d\.]+)\)', line_str) or (re.search(r'\(\$?([\d\.]+)\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1))
                key = f"cargo_{val}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'Insurance refund', 'DESCRIPTION': f'Deduction | CARGO INSURANCE @ (${val:.2f})', 'AMOUNT': -abs(val)})

        # Checking EFS
        elif 'EFS #' in line_str:
            amt_match = re.search(r'\(\$?([\d\.]+)\)', line_str) or (re.search(r'\(\$?([\d\.]+)\)', lines[i+1]) if i+1 < len(lines) else None) or (re.search(r'\(\$?([\d\.]+)\)', lines[i+2]) if i+2 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1))
                key = f"efs_{val}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'Driver loan Clearing', 'DESCRIPTION': f'Deduction | MONEY CODE @ (${val:.2f})', 'AMOUNT': -abs(val)})

        # Checking Short pay / Other (Deductions)
        elif 'SHORT PAY' in line_str.upper() or 'OTHER' in line_str.upper():
            amt_match = re.search(r'\(\$?([\d\.]+)\)', line_str) or (re.search(r'\(\$?([\d\.]+)\)', lines[i+1]) if i+1 < len(lines) else None) or (re.search(r'\(\$?([\d\.]+)\)', lines[i+2]) if i+2 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1))
                key = f"other_{val}_{i}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    desc_label = 'SHORT PAY' if 'SHORT PAY' in line_str.upper() else 'OTHER'
                    data.append({'CATEGORY': 'Driver loan Clearing', 'DESCRIPTION': f'Deduction | {desc_label} @ (${val:.2f})', 'AMOUNT': -abs(val)})

        # Checking Tolls
        elif 'Toll' in line_str or 'Tolls' in line_str:
            amt_match = re.search(r'\(\$?([\d\.]+)\)', line_str) or (re.search(r'\(\$?([\d\.]+)\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1))
                key = f"toll_{val}_{i}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'Driver loan Clearing', 'DESCRIPTION': f'Deduction | TOLLS @ (${val:.2f})', 'AMOUNT': -abs(val)})

        # Checking Deduction Type: OAI
        elif 'OAI' in line_str or 'Occupational accident' in line_str:
            amt_match = re.search(r'\(\$?([\d\.]+)\)', line_str) or (re.search(r'\(\$?([\d\.]+)\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1))
                key = f"oai_{val}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'Occupational Insurance Refund', 'DESCRIPTION': f'Deduction | OCCUPATIONAL ACCIDENT INSURANCE @ (${val:.2f})', 'AMOUNT': -abs(val)})

        # Checking Deduction Type/Advances: FEE / FUEL / Additives / Carrier / Discount
        elif 'FEE' in line_str or 'FUEL' in line_str or 'Fuel additives' in line_str or 'Carrier fee' in line_str or 'Discount' in line_str:
            amt_match = re.search(r'\(\$?([\d\.]+)\)', line_str) or (re.search(r'\(\$?([\d\.]+)\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1))
                key = f"fuel_adv_{val}_{i}"
                if key not in seen_deductions and val > 0:
                    seen_deductions.add(key)
                    loc_match = re.search(r'([A-Za-z\s,#0-9]+?)(?:FUEL|FEE)', line_str)
                    loc = loc_match.group(1).strip() if loc_match else "Fuel Station"
                    data.append({'CATEGORY': 'Prepaid Fuel', 'DESCRIPTION': f'Fuel | {loc} @ (${val:.2f})', 'AMOUNT': -abs(val)})

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
