"""
BOT KEUANGAN LENGKAP - TELEGRAM
Fitur: OCR Foto, PDF, Voice Note (FIXED)
"""

import os
import re
import json
import tempfile
import subprocess
from datetime import datetime

import gspread
from PIL import Image
import pytesseract
from pypdf import PdfReader
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, 
    MessageHandler, filters, ContextTypes
)

# ==================== KONFIGURASI ====================
TELEGRAM_TOKEN = "8490742379:AAGFGInz2LPIW9zJH6NnNUUkCGe81pvMFC0"
SPREADSHEET_NAME = "Keuangan pribadi"
BUDGET_FILE = "budget_data.json"

# Path Tesseract
tesseract_paths = [
    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
]
for path in tesseract_paths:
    if os.path.exists(path):
        pytesseract.pytesseract.tesseract_cmd = path
        break

# Deteksi file credentials
if os.path.exists("credentials.json"):
    CREDENTIALS_FILE = "credentials.json"
elif os.path.exists("credentials.json.json"):
    CREDENTIALS_FILE = "credentials.json.json"
else:
    CREDENTIALS_FILE = "credentials.json"

# ==================== KATEGORI ====================
KATEGORI = {
    "🍔 Makanan": ["makan", "restoran", "cafe", "kopi", "jajan", "bakso", "nasi", "gorengan", "sarapan"],
    "🚗 Transportasi": ["gojek", "grab", "bensin", "tol", "taxi", "ojek", "angkot"],
    "🛒 Belanja": ["belanja", "alfamart", "indomaret", "minimarket", "sembako"],
    "🏠 Cicilan": ["sewa", "cicil", "kpr", "rumah"],
    "💡 Tagihan": ["listrik", "air", "internet", "pulsa", "wifi"],
    "👶 Kebutuhan": ["popok", "susu", "obat", "bayi"],
    "🎮 Hiburan": ["nonton", "game", "netflix", "wisata"],
    "❓ Lainnya": []
}

# ==================== FUNGSI BANTUAN ====================
def format_uang(angka):
    return f"Rp {angka:,.0f}".replace(",", ".")

def parse_nominal(text):
    text = text.lower().strip()
    
    # Deteksi JUTA
    if "jt" in text or "juta" in text:
        match = re.search(r'(\d+(?:[.,]\d+)?)', text)
        if match:
            nilai = float(match.group(1).replace(",", "."))
            return int(nilai * 1000000)
    
    # Deteksi RIBU
    if "rb" in text or "ribu" in text or "k" in text:
        match = re.search(r'(\d+(?:[.,]\d+)?)', text)
        if match:
            nilai = float(match.group(1).replace(",", "."))
            return int(nilai * 1000)
    
    # Angka biasa
    match = re.search(r'(\d+)', text)
    if match:
        return int(match.group(1))
    return None

def get_category_from_text(deskripsi):
    deskripsi_lower = deskripsi.lower()
    for kat, keywords in KATEGORI.items():
        if any(kw in deskripsi_lower for kw in keywords):
            return kat
    return "❓ Lainnya"

def ambil_deskripsi(teks, nominal):
    if nominal >= 1000000:
        teks = re.sub(rf'{nominal//1000000}jt', '', teks)
        teks = re.sub(rf'{nominal//1000000} juta', '', teks)
    if nominal >= 1000:
        teks = re.sub(rf'{nominal//1000}rb', '', teks)
        teks = re.sub(rf'{nominal//1000} ribu', '', teks)
        teks = re.sub(rf'{nominal//1000}k', '', teks)
    teks = re.sub(rf'{nominal}', '', teks)
    teks = re.sub(r'[^\w\s]', '', teks)
    teks = teks.strip()
    return teks if teks else "transaksi"

# ==================== OCR FUNCTIONS ====================
def ocr_image(file_path):
    try:
        image = Image.open(file_path)
        image = image.convert('L')
        text = pytesseract.image_to_string(image, lang='ind+eng')
        return text
    except Exception as e:
        print(f"OCR Image error: {e}")
        return None

def ocr_pdf(file_path):
    try:
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text()
        return text
    except Exception as e:
        print(f"OCR PDF error: {e}")
        return None

# ==================== VOICE NOTE FUNCTIONS ====================
def convert_ogg_to_wav(ogg_path, wav_path):
    """Konversi OGG ke WAV menggunakan ffmpeg"""
    try:
        cmd = ['ffmpeg', '-i', ogg_path, '-acodec', 'pcm_s16le', '-ar', '16000', wav_path, '-y']
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode == 0
    except Exception as e:
        print(f"Konversi error: {e}")
        return False

def transcribe_voice(file_path):
    """Transkripsi voice note ke teks"""
    try:
        import speech_recognition as sr
        
        # Konversi ke WAV jika file OGG
        if file_path.endswith('.ogg'):
            wav_path = file_path.replace('.ogg', '.wav')
            if not convert_ogg_to_wav(file_path, wav_path):
                return None
            file_path = wav_path
        
        recognizer = sr.Recognizer()
        with sr.AudioFile(file_path) as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = recognizer.record(source)
            text = recognizer.recognize_google(audio, language='id-ID')
            return text
            
    except ImportError:
        return None
    except Exception as e:
        print(f"Transkripsi error: {e}")
        return None

def extract_info_from_ocr(text):
    if not text:
        return None, None
    
    nominal = None
    patterns = [
        r'total[:\s]*Rp?[.\s]*(\d+(?:[.,]\d+)?)',
        r'jumlah[:\s]*Rp?[.\s]*(\d+(?:[.,]\d+)?)',
        r'bayar[:\s]*Rp?[.\s]*(\d+(?:[.,]\d+)?)',
        r'(\d+(?:[.,]\d+)?)\s*(?:rupiah|rb|ribu)',
        r'Rp[.\s]*(\d+(?:[.,]\d+)?)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            raw = match.group(1).replace(",", "").replace(".", "")
            nominal = int(raw)
            break
    
    if not nominal:
        numbers = re.findall(r'(\d+(?:[.,]\d+)?)', text)
        numbers = [int(n.replace(",", "").replace(".", "")) for n in numbers]
        if numbers:
            nominal = max(numbers)
    
    lines = text.strip().split('\n')
    merchant = "Toko"
    for line in lines[:5]:
        line = line.strip()
        if len(line) > 3 and not re.match(r'^\d+', line):
            merchant = line[:30]
            break
    
    return nominal, merchant

# ==================== GOOGLE SHEETS ====================
def get_sheet():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        return client.open(SPREADSHEET_NAME).sheet1
    except Exception as e:
        print(f"Sheet error: {e}")
        return None

def simpan_transaksi(tanggal, tipe, kategori, nominal, deskripsi):
    sheet = get_sheet()
    if not sheet:
        return None
    
    if not sheet.get_all_values():
        sheet.append_row(["ID", "Tanggal", "Tipe", "Kategori", "Nominal", "Deskripsi", "Bulan", "Tahun"])
    
    data = sheet.get_all_values()
    id_baru = len(data)
    
    row = [
        id_baru,
        tanggal.strftime("%Y-%m-%d %H:%M:%S"),
        tipe,
        kategori,
        nominal,
        deskripsi[:50],
        tanggal.strftime("%B"),
        tanggal.strftime("%Y")
    ]
    sheet.append_row(row)
    return id_baru

def ambil_transaksi(limit=100):
    sheet = get_sheet()
    if not sheet:
        return []
    data = sheet.get_all_values()
    if len(data) <= 1:
        return []
    
    hasil = []
    for row in data[1:]:
        if len(row) >= 5:
            try:
                hasil.append({
                    "id": int(row[0]),
                    "tanggal": datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S"),
                    "tipe": row[2],
                    "kategori": row[3],
                    "nominal": int(float(row[4])),
                    "deskripsi": row[5],
                    "bulan": row[6] if len(row) > 6 else "",
                    "tahun": row[7] if len(row) > 7 else ""
                })
            except:
                continue
    hasil.sort(key=lambda x: x["tanggal"], reverse=True)
    return hasil[:limit]

def hapus_transaksi(id_transaksi):
    sheet = get_sheet()
    if not sheet:
        return False
    data = sheet.get_all_values()
    for i, row in enumerate(data[1:], start=2):
        if len(row) > 0 and str(row[0]) == str(id_transaksi):
            sheet.delete_rows(i)
            return True
    return False

def hapus_beberapa_transaksi(ids):
    berhasil = 0
    for id_transaksi in ids:
        if hapus_transaksi(id_transaksi):
            berhasil += 1
    return berhasil

def parse_hapus_ids(teks):
    ids = set()
    
    range_match = re.search(r'(\d+)\s*[-–]\s*(\d+)', teks)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        for i in range(start, end + 1):
            ids.add(i)
        return sorted(ids)
    
    parts = re.split(r'[,\s]+', teks)
    for part in parts:
        if part.isdigit():
            ids.add(int(part))
    
    return sorted(ids)

def ringkasan_bulan_ini():
    now = datetime.now()
    bulan_ini = now.strftime("%B")
    tahun_ini = now.strftime("%Y")
    
    sheet = get_sheet()
    if not sheet:
        return 0, 0, 0, {}
    
    data = sheet.get_all_values()
    if len(data) <= 1:
        return 0, 0, 0, {}
    
    pemasukan = 0
    pengeluaran = 0
    kategori_total = {}
    
    for row in data[1:]:
        if len(row) >= 8:
            try:
                if row[6] == bulan_ini and row[7] == tahun_ini:
                    nominal = int(float(row[4]))
                    if row[2] == "pemasukan":
                        pemasukan += nominal
                    else:
                        pengeluaran += nominal
                        kategori_total[row[3]] = kategori_total.get(row[3], 0) + nominal
            except:
                continue
    
    return pemasukan, pengeluaran, pemasukan - pengeluaran, kategori_total

def ringkasan_hari_ini():
    today = datetime.now().strftime("%Y-%m-%d")
    transaksi = ambil_transaksi(limit=200)
    
    pemasukan = 0
    pengeluaran = 0
    detail = []
    
    for t in transaksi:
        if t["tanggal"].strftime("%Y-%m-%d") == today:
            if t["tipe"] == "pemasukan":
                pemasukan += t["nominal"]
            else:
                pengeluaran += t["nominal"]
                detail.append(f"  • {t['deskripsi'][:25]}: {format_uang(t['nominal'])}")
    
    return pemasukan, pengeluaran, pemasukan - pengeluaran, detail

# ==================== BUDGET ====================
def load_budget():
    if os.path.exists(BUDGET_FILE):
        try:
            with open(BUDGET_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_budget(data):
    try:
        with open(BUDGET_FILE, 'w') as f:
            json.dump(data, f)
        return True
    except:
        return False

def get_daily_budget(user_id):
    data = load_budget()
    user_id_str = str(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    if user_id_str in data and data[user_id_str].get("date") == today:
        return data[user_id_str].get("budget", 0), data[user_id_str].get("spent", 0)
    return None, 0

def set_daily_budget(user_id, budget):
    data = load_budget()
    user_id_str = str(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    _, pengeluaran, _, _ = ringkasan_hari_ini()
    data[user_id_str] = {"budget": budget, "date": today, "spent": pengeluaran}
    save_budget(data)
    return True

def update_daily_spent(user_id):
    data = load_budget()
    user_id_str = str(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    _, pengeluaran, _, _ = ringkasan_hari_ini()
    
    if user_id_str not in data or data[user_id_str].get("date") != today:
        data[user_id_str] = {"budget": 0, "date": today, "spent": pengeluaran}
    else:
        data[user_id_str]["spent"] = pengeluaran
    
    save_budget(data)
    budget = data[user_id_str].get("budget", 0)
    remaining = budget - pengeluaran
    percent = int((pengeluaran / budget) * 100) if budget > 0 else 0
    return budget, pengeluaran, remaining, percent

# ==================== HANDLER TELEGRAM ====================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nama = update.effective_user.first_name
    text = f"""
💰 *Halo {nama}!*

*BOT KEUANGAN LENGKAP*

📸 *Kirim FOTO STRUK* → Otomatis baca
📄 *Kirim FILE PDF* → Otomatis baca
🎤 *Kirim VOICE NOTE* → Otomatis baca

📝 *CATAT MANUAL:*
`makan 20000` → pengeluaran
`gaji 5jt` → pemasukan

📊 *PERINTAH:*
`laporan` → bulan ini
`hari ini` → hari ini
`budget 100000` → set budget
`sisa` → cek budget
`riwayat` → lihat transaksi
`hapus 1` → hapus ID 1
`hapus 1,2,3` → hapus banyak
`hapus 1-5` → hapus range
`bantuan` → panduan
    """
    await update.message.reply_text(text, parse_mode="Markdown")

async def bantuan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
📖 *PANDUAN LENGKAP*

*📸 DETEKSI STRUK:*
• Kirim FOTO struk → auto baca
• Kirim FILE PDF struk → auto baca
• Kirim VOICE NOTE → auto baca

*📝 CATAT MANUAL:*
`makan 20000` - pengeluaran
`gaji 5jt` - pemasukan

*📊 PERINTAH:*
`laporan` - Rekap bulan ini
`hari ini` - Rekap hari ini
`riwayat` - 15 transaksi terakhir
`budget 100000` - Set budget
`sisa` - Cek sisa budget

*🗑️ HAPUS:*
`hapus 1` - Hapus ID 1
`hapus 1,2,3` - Hapus banyak
`hapus 1-5` - Hapus range

*🎤 CONTOH VOICE NOTE:*
• "beli makan 20 ribu"
• "bensin 50rb"
• "gaji 5 juta"
    """
    await update.message.reply_text(text, parse_mode="Markdown")

async def laporan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pemasukan, pengeluaran, sisa, kategori = ringkasan_bulan_ini()
    now = datetime.now()
    
    text = f"""
📊 *LAPORAN BULAN INI*
{now.strftime('%B %Y')}
━━━━━━━━━━━━━━━━━━━━━━━

💰 *Pemasukan:* {format_uang(pemasukan)}
💸 *Pengeluaran:* {format_uang(pengeluaran)}
💵 *Sisa Saldo:* {format_uang(sisa)}

📂 *RINCIAN KATEGORI:*
"""
    if kategori:
        sorted_kat = sorted(kategori.items(), key=lambda x: x[1], reverse=True)
        for kat, total in sorted_kat[:5]:
            persen = int((total / pengeluaran) * 100) if pengeluaran > 0 else 0
            text += f"\n{kat}: {format_uang(total)} ({persen}%)"
    else:
        text += "\nBelum ada transaksi bulan ini."
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def hari_ini_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pemasukan, pengeluaran, sisa, detail = ringkasan_hari_ini()
    now = datetime.now()
    user_id = update.effective_user.id
    
    text = f"""
📅 *LAPORAN HARI INI*
{now.strftime('%A, %d %B %Y')}
━━━━━━━━━━━━━━━━━━━━━━━

💰 *Pemasukan:* {format_uang(pemasukan)}
💸 *Pengeluaran:* {format_uang(pengeluaran)}
💵 *Sisa Saldo:* {format_uang(sisa)}
"""
    budget, spent = get_daily_budget(user_id)
    if budget:
        sisa_budget = budget - spent
        percent = int((spent / budget) * 100) if budget > 0 else 0
        text += f"\n🎯 *Budget:* {format_uang(budget)}"
        text += f"\n✅ *Sisa Budget:* {format_uang(sisa_budget)} ({percent}%)"
    
    if detail:
        text += f"\n\n📝 *Detail:*\n" + "\n".join(detail[:10])
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def riwayat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    transaksi = ambil_transaksi(limit=15)
    if not transaksi:
        await update.message.reply_text("📭 *Belum ada transaksi.*", parse_mode="Markdown")
        return
    
    text = "📋 *RIWAYAT TRANSAKSI*\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for t in transaksi[:15]:
        emoji = "🔻" if t["tipe"] == "pengeluaran" else "🔼"
        text += f"{emoji} *ID {t['id']}* | {t['tanggal'].strftime('%d/%m %H:%M')}\n"
        text += f"   {t['deskripsi'][:30]}\n"
        text += f"   {format_uang(t['nominal'])} [{t['kategori']}]\n\n"
    
    text += "━━━━━━━━━━━━━━━━━━━━━━━\n"
    text += "💡 `hapus 1` atau `hapus 1,2,3` atau `hapus 1-5`"
    await update.message.reply_text(text, parse_mode="Markdown")

async def budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("📌 `budget 100000` atau `budget 50rb`", parse_mode="Markdown")
        return
    
    nominal = parse_nominal(" ".join(context.args))
    if not nominal or nominal <= 0:
        await update.message.reply_text("❌ Format salah!", parse_mode="Markdown")
        return
    
    set_daily_budget(update.effective_user.id, nominal)
    await update.message.reply_text(f"✅ *Budget harian: {format_uang(nominal)}*", parse_mode="Markdown")

async def sisa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    budget, spent = get_daily_budget(user_id)
    
    if not budget:
        await update.message.reply_text("⚠️ *Belum set budget.*\n`budget 100000`", parse_mode="Markdown")
        return
    
    sisa_budget = budget - spent
    percent = int((spent / budget) * 100) if budget > 0 else 0
    
    text = f"""
🎯 *STATUS BUDGET*

💰 Budget: {format_uang(budget)}
💸 Terpakai: {format_uang(spent)}
✅ Sisa: {format_uang(sisa_budget)}
📊 {percent}% terpakai
"""
    if sisa_budget < 0:
        text += "\n⚠️ *OVERBUDGET!*"
    elif percent >= 90:
        text += "\n⚠️ *Budget hampir habis!*"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def hapus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("📌 `hapus 1` atau `hapus 1,2,3` atau `hapus 1-5`", parse_mode="Markdown")
        return
    
    teks = " ".join(context.args)
    ids = parse_hapus_ids(teks)
    
    if not ids:
        await update.message.reply_text("❌ Format salah! Contoh: `hapus 1,2,3`", parse_mode="Markdown")
        return
    
    berhasil = hapus_beberapa_transaksi(ids)
    
    if berhasil > 0:
        update_daily_spent(update.effective_user.id)
        await update.message.reply_text(f"✅ *Berhasil menghapus {berhasil} transaksi!*", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ *Tidak ada transaksi yang dihapus!*", parse_mode="Markdown")

# ==================== HANDLER FILE, FOTO & VOICE ====================
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk voice note dengan konversi OGG ke WAV"""
    processing_msg = await update.message.reply_text(
        "🎤 *Memproses voice note...*\n⏳ (5-10 detik)", 
        parse_mode="Markdown"
    )
    
    try:
        file = await update.message.voice.get_file()
        
        # Download file OGG
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
            await file.download_to_drive(tmp.name)
            ogg_path = tmp.name
        
        # Transkrip voice
        text = transcribe_voice(ogg_path)
        
        # Hapus file temporary
        try:
            os.unlink(ogg_path)
            wav_path = ogg_path.replace('.ogg', '.wav')
            if os.path.exists(wav_path):
                os.unlink(wav_path)
        except:
            pass
        
        if text:
            print(f"Voice recognized: {text}")
            nominal = parse_nominal(text)
            
            if nominal and nominal > 0:
                tipe = "pengeluaran"
                deskripsi = text[:50]
                kategori = get_category_from_text(text)
                
                simpan_transaksi(datetime.now(), tipe, kategori, nominal, deskripsi)
                update_daily_spent(update.effective_user.id)
                
                await processing_msg.edit_text(
                    f"🔻 *PENGELUARAN dari VOICE!*\n\n"
                    f"📝 *'{text[:60]}'*\n"
                    f"💰 *Nominal:* {format_uang(nominal)}\n"
                    f"📂 *Kategori:* {kategori}\n\n"
                    f"✅ Tersimpan!",
                    parse_mode="Markdown"
                )
            else:
                await processing_msg.edit_text(
                    f"📝 *'{text[:80]}'*\n\n"
                    f"❌ *Tidak ditemukan nominal!*\n\n"
                    f"Contoh: 'beli makan 20 ribu'\n\n"
                    f"Coba catat manual: `makan 20000`",
                    parse_mode="Markdown"
                )
        else:
            await processing_msg.edit_text(
                "❌ *Tidak dapat mengenali suara!*\n\n"
                "Pastikan:\n"
                "✓ Ucapan jelas\n"
                "✓ Bahasa Indonesia\n"
                "✓ Suara cukup keras\n\n"
                "Atau catat manual: `makan 20000`",
                parse_mode="Markdown"
            )
            
    except Exception as e:
        print(f"Voice handler error: {e}")
        await processing_msg.edit_text(
            "❌ *Gagal memproses voice note!*\n\n"
            "Coba catat manual: `makan 20000`",
            parse_mode="Markdown"
        )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    processing_msg = await update.message.reply_text("📄 *Membaca file PDF...*", parse_mode="Markdown")
    
    try:
        file = await update.message.document.get_file()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            await file.download_to_drive(tmp.name)
            tmp_path = tmp.name
        
        text = ocr_pdf(tmp_path)
        os.unlink(tmp_path)
        
        if text:
            nominal, merchant = extract_info_from_ocr(text)
            if nominal and nominal > 0:
                tipe = "pengeluaran"
                deskripsi = f"{merchant} (PDF)"
                kategori = get_category_from_text(text)
                
                simpan_transaksi(datetime.now(), tipe, kategori, nominal, deskripsi)
                update_daily_spent(update.effective_user.id)
                
                await processing_msg.edit_text(
                    f"🔻 *PENGELUARAN dari PDF!*\n\n"
                    f"🏪 *Toko:* {merchant}\n"
                    f"💰 *Total:* {format_uang(nominal)}\n"
                    f"📂 *Kategori:* {kategori}\n\n✅ Tersimpan!",
                    parse_mode="Markdown"
                )
            else:
                await processing_msg.edit_text("❌ *Tidak dapat membaca nominal!*", parse_mode="Markdown")
        else:
            await processing_msg.edit_text("❌ *Gagal membaca PDF!*", parse_mode="Markdown")
    except Exception as e:
        print(f"Error: {e}")
        await processing_msg.edit_text("❌ *Gagal memproses file!*", parse_mode="Markdown")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    processing_msg = await update.message.reply_text("📸 *Membaca foto struk...*", parse_mode="Markdown")
    
    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            await file.download_to_drive(tmp.name)
            tmp_path = tmp.name
        
        text = ocr_image(tmp_path)
        os.unlink(tmp_path)
        
        if text:
            nominal, merchant = extract_info_from_ocr(text)
            if nominal and nominal > 0:
                tipe = "pengeluaran"
                deskripsi = merchant
                kategori = get_category_from_text(text)
                
                simpan_transaksi(datetime.now(), tipe, kategori, nominal, deskripsi)
                update_daily_spent(update.effective_user.id)
                
                await processing_msg.edit_text(
                    f"🔻 *PENGELUARAN dari STRUK!*\n\n"
                    f"🏪 *Toko:* {merchant}\n"
                    f"💰 *Total:* {format_uang(nominal)}\n"
                    f"📂 *Kategori:* {kategori}\n\n✅ Tersimpan!",
                    parse_mode="Markdown"
                )
            else:
                await processing_msg.edit_text("❌ *Tidak dapat membaca nominal!*", parse_mode="Markdown")
        else:
            await processing_msg.edit_text("❌ *Gagal membaca foto!* Pastikan foto jelas.", parse_mode="Markdown")
    except Exception as e:
        print(f"Error: {e}")
        await processing_msg.edit_text("❌ *Gagal memproses foto!*", parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower().strip()
    user_id = update.effective_user.id
    
    if text.startswith('/'):
        return
    
    nominal = parse_nominal(text)
    
    if nominal and nominal > 0:
        if any(word in text for word in ["gaji", "bonus", "dapat", "terima"]):
            tipe = "pemasukan"
        else:
            tipe = "pengeluaran"
        
        deskripsi = ambil_deskripsi(text, nominal)
        kategori = get_category_from_text(deskripsi)
        
        simpan_transaksi(datetime.now(), tipe, kategori, nominal, deskripsi)
        
        emoji = "🔻" if tipe == "pengeluaran" else "🔼"
        response = f"{emoji} *{tipe.upper()}*: {deskripsi}\n💰 {format_uang(nominal)}\n📂 {kategori}"
        
        if tipe == "pengeluaran":
            budget, spent, remaining, percent = update_daily_spent(user_id)
            if budget > 0:
                response += f"\n🎯 *Sisa Budget:* {format_uang(remaining)}"
                if remaining < 0:
                    response += f"\n⚠️ *OVERBUDGET!*"
                elif percent >= 90:
                    response += f"\n⚠️ *Budget hampir habis!*"
        else:
            update_daily_spent(user_id)
        
        await update.message.reply_text(response, parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "❌ *Format tidak dikenali*\n\n"
            "📸 *Kirim FOTO STRUK* → auto detect\n"
            "📄 *Kirim FILE PDF* → auto detect\n"
            "🎤 *Kirim VOICE NOTE* → auto detect\n"
            "📝 *Atau tulis:* `makan 20000`\n\n"
            "Ketik `bantuan` untuk panduan",
            parse_mode="Markdown"
        )

# ==================== MAIN ====================
def main():
    if not os.path.exists(CREDENTIALS_FILE):
        print("\n❌ ERROR: File credentials.json tidak ditemukan!")
        return
    
    # Cek FFmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True)
        print("✅ FFmpeg terdeteksi")
    except:
        print("\n⚠️ PERINGATAN: FFmpeg tidak ditemukan!")
        print("Voice note TIDAK akan bekerja tanpa FFmpeg!")
        print("Download: https://www.gyan.dev/ffmpeg/builds/")
        print("Install dan tambahkan ke PATH\n")
    
    print("\n✅ Bot berhasil dijalankan!")
    print(f"📁 Credentials: {CREDENTIALS_FILE}")
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("bantuan", bantuan_command))
    app.add_handler(CommandHandler("laporan", laporan_command))
    app.add_handler(CommandHandler("hari", hari_ini_command))
    app.add_handler(CommandHandler("riwayat", riwayat_command))
    app.add_handler(CommandHandler("budget", budget_command))
    app.add_handler(CommandHandler("sisa", sisa_command))
    app.add_handler(CommandHandler("hapus", hapus_command))
    
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("📱 Bot siap menerima pesan!")
    print("🎤 Voice note: ON (wajib FFmpeg)")
    app.run_polling(poll_interval=0.5)

if __name__ == "__main__":
    main()