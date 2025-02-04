import os
import json
import sqlite3
import csv
from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Sozlamalarni yuklash
TOKEN = os.getenv('7961321780:AAHBfG03GnP3pYX1rj5E8_gGxzTdapQcD28')
WEBHOOK_URL = os.getenv('https://dostbot.up.railway.app')
CHANNEL_ID = os.getenv('@users1dt')
ADMINS = [int(id) for id in os.getenv('ADMINS').split(',')]

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Database konfiguratsiyasi
conn = sqlite3.connect('quiz.db', check_same_thread=False)
cursor = conn.cursor()

# Database jadvallarini yaratish (avtomatik yangilanadi)
cursor.execute('''CREATE TABLE IF NOT EXISTS users
               (id INTEGER PRIMARY KEY, 
               username TEXT, 
               answers TEXT, 
               completed INTEGER DEFAULT 0,
               blocked INTEGER DEFAULT 0,
               last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS questions
               (id INTEGER PRIMARY KEY AUTOINCREMENT,
               question_text TEXT,
               options TEXT,
               active INTEGER DEFAULT 1)''')

conn.commit()

# Savollarni yuklash
def load_questions():
    cursor.execute("SELECT * FROM questions WHERE active = 1 ORDER BY id")
    return [{"text": row[1], "options": json.loads(row[2])} for row in cursor.fetchall()]

questions = load_questions()

# Webhook endpoints
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    return 'Bad Request', 400

@app.route('/')
def setup_webhook():
    bot.remove_webhook()
    bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    return 'Webhook muvaffaqiyatli o\'rnatildi!'

# Asosiy bot funksiyalari
@bot.message_handler(commands=['start'])
def start(message):
    if message.from_user.id in ADMINS:
        return admin_panel(message)
        
    cursor.execute("INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)", 
                 (message.chat.id, message.from_user.username))
    conn.commit()
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Testni boshlash 🚀", callback_data="start_test"))
    bot.send_message(message.chat.id, "Salom! Do'stlik testiga xush kelibsiz!", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "start_test")
def start_test(call):
    user_id = call.from_user.id
    cursor.execute("SELECT blocked FROM users WHERE id = ?", (user_id,))
    if cursor.fetchone()[0] == 1:
        return bot.answer_callback_query(call.id, "❌ Siz bloklangansiz!", show_alert=True)
    
    cursor.execute("UPDATE users SET answers = '[]', completed = 0 WHERE id = ?", (user_id,))
    conn.commit()
    send_question(user_id, 0)

def send_question(chat_id, step):
    if step < len(questions):
        question = questions[step]
        markup = InlineKeyboardMarkup()
        for option in question["options"]:
            markup.add(InlineKeyboardButton(option, callback_data=f"answer_{step}_{option}"))
        bot.send_message(chat_id, f"{step+1}-savol: {question['text']}", reply_markup=markup)
    else:
        cursor.execute("UPDATE users SET completed = 1 WHERE id = ?", (chat_id,))
        conn.commit()
        send_results(chat_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("answer_"))
def handle_answer(call):
    user_id = call.from_user.id
    cursor.execute("SELECT blocked FROM users WHERE id = ?", (user_id,))
    if cursor.fetchone()[0] == 1:
        return bot.answer_callback_query(call.id, "❌ Siz bloklangansiz!", show_alert=True)
    
    _, step, answer = call.data.split('_', 2)
    step = int(step)
    
    cursor.execute("SELECT answers FROM users WHERE id = ?", (user_id,))
    answers = json.loads(cursor.fetchone()[0])
    answers.append(answer)
    
    cursor.execute("UPDATE users SET answers = ?, last_activity = CURRENT_TIMESTAMP WHERE id = ?", 
                 (json.dumps(answers), user_id))
    conn.commit()
    
    bot.delete_message(call.message.chat.id, call.message.message_id)
    send_question(user_id, step+1)

def send_results(chat_id):
    cursor.execute("SELECT answers FROM users WHERE id = ?", (chat_id,))
    answers = json.loads(cursor.fetchone()[0])
    
    result_text = "📊 Test natijalaringiz:\n\n"
    for i, (q, a) in enumerate(zip(questions, answers)):
        result_text += f"{i+1}. {q['text']}: {a}\n"
    
    try:
        user_info = bot.get_chat(chat_id)
        user_name = user_info.first_name or "Foydalanuvchi"
        mention = f"<a href='tg://user?id={chat_id}'>{user_name}</a>"
        bot.send_message(CHANNEL_ID, f"🎉 {mention} yangi test natijasini yubordi!\n\n{result_text}", parse_mode='HTML')
    except Exception as e:
        print(f"Xatolik yuz berdi: {e}")
    
    bot.send_message(chat_id, result_text)

# Admin panel va yangi funksiyalar
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id not in ADMINS:
        return
    
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [
        InlineKeyboardButton("📈 Statistika", callback_data="admin_stats"),
        InlineKeyboardButton("📤 Xabar yuborish", callback_data="admin_broadcast"),
        InlineKeyboardButton("📝 Savol qo'shish", callback_data="admin_add_question"),
        InlineKeyboardButton("📋 Savollar", callback_data="admin_list_questions"),
        InlineKeyboardButton("🚫 Bloklash", callback_data="admin_block_user"),
        InlineKeyboardButton("📊 Real vaqt", callback_data="admin_stats_live")
    ]
    markup.add(*buttons)
    bot.send_message(message.chat.id, "🔐 Admin panel:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def admin_actions(call):
    if call.from_user.id not in ADMINS:
        return
    
    action = call.data.split('_')[1]
    
    if action == "stats":
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE completed = 1")
        completed_users = cursor.fetchone()[0]
        
        text = f"📊 Statistika:\n\n👥 Umumiy foydalanuvchilar: {total_users}\n✅ Test tamomlaganlar: {completed_users}"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id)
    
    elif action == "broadcast":
        msg = bot.send_message(call.message.chat.id, "📩 Xabarni kiriting:")
        bot.register_next_step_handler(msg, process_broadcast)
    
    elif action == "add_question":
        msg = bot.send_message(call.message.chat.id, "❓ Yangi savol formatini kiriting:\nSavol matni|variant1,variant2,variant3")
        bot.register_next_step_handler(msg, process_new_question)
    
    elif action == "list_questions":
        list_questions(call.message)
    
    elif action == "block_user":
        msg = bot.send_message(call.message.chat.id, "🚫 Bloklanadigan foydalanuvchi ID sini kiriting:")
        bot.register_next_step_handler(msg, process_block_user)
    
    elif action == "stats_live":
        live_stats(call.message)

def process_block_user(message):
    try:
        user_id = int(message.text)
        cursor.execute("UPDATE users SET blocked = 1 WHERE id = ?", (user_id,))
        conn.commit()
        bot.reply_to(message, f"✅ {user_id} bloklandi!")
    except:
        bot.reply_to(message, "❌ Noto'g'ri format! Faqat raqam kiriting.")

def process_broadcast(message):
    users = cursor.execute("SELECT id FROM users WHERE blocked = 0").fetchall()
    success = 0
    for user in users:
        try:
            bot.send_message(user[0], message.text)
            success += 1
        except:
            continue
    bot.send_message(message.chat.id, f"📤 Xabar {success}/{len(users)} foydalanuvchiga yetkazildi")

def process_new_question(message):
    try:
        text, options = message.text.split('|')
        options = [opt.strip() for opt in options.split(',')]
        cursor.execute("INSERT INTO questions (question_text, options) VALUES (?, ?)",
                     (text.strip(), json.dumps(options)))
        conn.commit()
        global questions
        questions = load_questions()
        bot.reply_to(message, "✅ Savol qo'shildi!")
    except Exception as e:
        bot.reply_to(message, f"❌ Xato: {str(e)}")

def list_questions(message):
    cursor.execute("SELECT * FROM questions WHERE active = 1")
    questions_list = cursor.fetchall()
    
    markup = InlineKeyboardMarkup()
    for q in questions_list:
        btn_text = f"{q[0]}. {q[1][:20]}..." if len(q[1]) > 20 else f"{q[0]}. {q[1]}"
        markup.add(InlineKeyboardButton(btn_text, callback_data=f"edit_select_{q[0]}"))
    
    bot.send_message(message.chat.id, "📋 Faol savollar:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_select_"))
def edit_select_handler(call):
    question_id = int(call.data.split('_')[2])
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"edit_edit_{question_id}"),
        InlineKeyboardButton("🗑 O'chirish", callback_data=f"edit_delete_{question_id}")
    )
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_"))
def edit_question_handler(call):
    action, question_id = call.data.split('_')[1:]
    question_id = int(question_id)
    
    if action == "delete":
        cursor.execute("UPDATE questions SET active = 0 WHERE id = ?", (question_id,))
        conn.commit()
        bot.edit_message_text("✅ Savol o'chirildi!", call.message.chat.id, call.message.message_id)
    elif action == "edit":
        msg = bot.send_message(call.message.chat.id, "Yangi savol matnini kiriting:")
        bot.register_next_step_handler(msg, process_question_edit, question_id)

def process_question_edit(message, question_id):
    try:
        new_text = message.text
        cursor.execute("UPDATE questions SET question_text = ? WHERE id = ?", 
                     (new_text, question_id))
        conn.commit()
        bot.reply_to(message, "✅ Savol yangilandi!")
    except Exception as e:
        bot.reply_to(message, f"❌ Xato: {str(e)}")

def live_stats(message):
    cursor.execute('''SELECT COUNT(*) FROM users 
                   WHERE blocked = 0 AND datetime(last_activity) > datetime('now', '-5 minutes')''')
    active_users = cursor.fetchone()[0]
    
    cursor.execute('''SELECT username, COUNT(*) as count FROM users 
                   WHERE completed = 1 GROUP BY username ORDER BY count DESC LIMIT 5''')
    top_users = cursor.fetchall()
    
    stats_text = f"📈 Real vaqt statistikasi:\n\n"
    stats_text += f"🟢 Faol foydalanuvchilar (5 minut): {active_users}\n"
    stats_text += "🏆 Top test ishlovchilar:\n"
    for i, (username, count) in enumerate(top_users):
        stats_text += f"{i+1}. @{username} - {count} marta\n"
    
    bot.send_message(message.chat.id, stats_text)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
