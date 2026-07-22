import os
import re
import pandas as pd
import pdfplumber
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.environ.get("BOT_TOKEN")

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

    # 2. DEDUCTIONS (Description va Deduction Type bo'yicha)
    # Formati: (Category, Pattern, Description Format)
    deduction_rules = [
        ('Admin Fee', r'Admin Fee[\s\S]*?\(\$?([\d\.]+)\)', 'Deduction | ADMINISTRATION FEE @ (${amount})'),
        ('Ifta', r'IFTA[\s\S]*?\(\$?([\d\.]+)\)', 'Deduction | IFTA @ (${amount})'),
        ('Insurance refund', r'Cargo Insurance[\s\S]*?\(\$?([\d\.]+)\)', 'Deduction | CARGO INSURANCE @ (${amount})'),
        ('Driver loan Clearing', r'EFS[\s\S]*?\(\$?([\d\.]+)\)', 'Deduction | MONEY CODE @ (${amount})'),
        ('Driver loan Clearing', r'short pay[\s\S]*?\(\$?([\d\.]+)\)', 'Deduction | OTHER @ (${amount})'),
        ('Driver loan Clearing', r'Toll[s]?[\s\S]*?\(\$?([\d\.]+)\)', 'Deduction | TOLLS @ (${amount})'),
        ('Occupational Insurance Refund', r'OAI[\s\S]*?\(\$?([\d\.]+)\)|Occupational accident[\s\S]*?\(\$?([\d\.]+)\)', 'Deduction | OCCUPATIONAL ACCIDENT INSURANCE @ (${amount})'),
        ('Prepaid Fuel', r'Unit:\s*\d+[\s\S]*?FEE\s+\(\$([\d\.]+)\)', 'Fuel | FEE @ (${amount})'),
        ('Prepaid Fuel', r'Unit:\s*\d+[\s\S]*?FUEL\s+\(\$([\d\.]+)\)', 'Fuel | FUEL @ (${amount})')
    ]

    seen_deductions = set()
    
    # Text-based dynamic parsing for Deductions
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

        # Checking short pay
        elif 'short pay' in line_str:
            amt_match = re.search(r'\(\$?([\d\.]+)\)', line_str) or (re.search(r'\(\$?([\d\.]+)\)', lines[i+1]) if i+1 < len(lines) else None) or (re.search(r'\(\$?([\d\.]+)\)', lines[i+2]) if i+2 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1))
                key = f"short_{val}"
                if key not in seen_deductions:
                    seen_deductions.add(key)
                    data.append({'CATEGORY': 'Driver loan Clearing', 'DESCRIPTION': f'Deduction | OTHER @ (${val:.2f})', 'AMOUNT': -abs(val)})

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

        # Checking Deduction Type: FEE / FUEL (Deductions va Advances uchun)
        elif 'FEE' in line_str or 'FUEL' in line_str or 'Fuel additives' in line_str or 'Carrier fee' in line_str or 'Discount' in line_str:
            amt_match = re.search(r'\(\$?([\d\.]+)\)', line_str) or (re.search(r'\(\$?([\d\.]+)\)', lines[i+1]) if i+1 < len(lines) else None)
            if amt_match:
                val = float(amt_match.group(1))
                key = f"fuel_adv_{val}_{i}"
                if key not in seen_deductions and val > 0:
                    seen_deductions.add(key)
                    # Joy va stansiya nomini ajratib olish
                    loc_match = re.search(r'([A-Za-z\s,#0-9]+?)(?:FUEL|FEE)', line_str)
                    loc = loc_match.group(1).strip() if loc_match else "Fuel Station"
                    data.append({'CATEGORY': 'Prepaid Fuel', 'DESCRIPTION': f'Fuel | {loc} @ (${val:.2f})', 'AMOUNT': -abs(val)})

    return pd.DataFrame(data)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Salom! PDF faylingizni yuboring, uni yangilangan mapping qoidalari bo'yicha Excelga o'tkazib beraman.")

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
    print("Bot ishga tushdi...")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.run_polling()