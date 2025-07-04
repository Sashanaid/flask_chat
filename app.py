from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_mysqldb import MySQL
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY') or 'your-secret-key-here'

# MySQL Configuration
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST') or '127.0.0.1'
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER') or 'root'
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD') or 'root'
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB') or 'messenger_db'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

mysql = MySQL(app)

# Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, email):
        self.id = id
        self.username = username
        self.email = email

@login_manager.user_loader
def load_user(user_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    if user:
        return User(id=user['id'], username=user['username'], email=user['email'])
    return None

# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('contacts'))
    return render_template('index.html')

@app.route('/contacts/<string:chat_type>/<int:chat_id>')
@app.route('/contacts')
@login_required
def contacts(chat_type=None, chat_id=None):
    # Ваш существующий код
    cur = mysql.connection.cursor()
    
    # Получаем список всех чатов
    cur.execute("""
        SELECT id, username, 'user' as type FROM users WHERE id != %s
        UNION
        SELECT id, name, 'group' as type FROM chat_groups
        JOIN group_members ON chat_groups.id = group_members.group_id
        WHERE group_members.user_id = %s
    """, (current_user.id, current_user.id))
    
    chats = cur.fetchall()
    cur.close()
    
    # Если передан chat_type и chat_id, открываем этот чат
    initial_chat = None
    if chat_type and chat_id:
        initial_chat = {'type': chat_type, 'id': chat_id}
    
    return render_template('contacts.html', chats=chats, initial_chat=initial_chat)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE username = %s OR email = %s", (username, email))
        existing_user = cur.fetchone()
        
        if existing_user:
            flash('Username or email already exists', 'danger')
            return redirect(url_for('register'))
        
        hashed_password = generate_password_hash(password)
        cur.execute("INSERT INTO users (username, email, password) VALUES (%s, %s, %s)", 
                   (username, email, hashed_password))
        mysql.connection.commit()
        cur.close()
        
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()
        
        if user and check_password_hash(user['password'], password):
            user_obj = User(id=user['id'], username=user['username'], email=user['email'])
            login_user(user_obj)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('contacts'))  # Изменено с chat на contacts
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('login.html')



@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Вы успешно вышли из системы', 'success')
    return redirect(url_for('index'))

@app.route('/chat')
@login_required
def chat():
    # Получаем список пользователей (исключая текущего)
    cur = mysql.connection.cursor()
    cur.execute("SELECT id, username FROM users WHERE id != %s", (current_user.id,))
    users = cur.fetchall()
    
    # Получаем последние сообщения
    cur.execute("""
        SELECT m.*, u.username as sender_name 
        FROM messages m 
        JOIN users u ON m.sender_id = u.id 
        WHERE m.receiver_id = %s OR m.sender_id = %s 
        ORDER BY m.timestamp DESC 
        LIMIT 20
    """, (current_user.id, current_user.id))
    messages = cur.fetchall()
    cur.close()
    
    return render_template('chat.html', users=users, messages=messages)



# Группы
@app.route('/groups')
@login_required
def groups():
    cur = mysql.connection.cursor()
    
    # 1. Запрос для групп, где пользователь является участником
    cur.execute("""
        SELECT g.*, u.username as creator_name 
        FROM chat_groups g
        JOIN users u ON g.created_by = u.id
        JOIN group_members gm ON g.id = gm.group_id
        WHERE gm.user_id = %s
    """, (current_user.id,))
    user_groups = cur.fetchall()
    
    # 2. Запрос для всех групп (с указанием, является ли пользователь участником)
    cur.execute("""
        SELECT g.*, u.username as creator_name,
               EXISTS(
                   SELECT 1 FROM group_members 
                   WHERE group_id = g.id AND user_id = %s
               ) as is_member
        FROM chat_groups g
        JOIN users u ON g.created_by = u.id
    """, (current_user.id,))
    all_groups = cur.fetchall()
    
    cur.close()
    return render_template('groups.html', user_groups=user_groups, all_groups=all_groups)

# Удаляем все маршруты, связанные с friend_requests
# Оставляем только работу с группами и сообщениями



@app.route('/get_chat_messages/<string:chat_type>/<int:chat_id>')
@login_required
def get_chat_messages(chat_type, chat_id):
    cur = mysql.connection.cursor()
    try:
        if chat_type == 'user':
            cur.execute("""
                SELECT m.*, u.username as sender_name 
                FROM messages m
                JOIN users u ON m.sender_id = u.id
                WHERE (m.sender_id = %s AND m.receiver_id = %s)
                   OR (m.sender_id = %s AND m.receiver_id = %s)
                ORDER BY m.timestamp DESC
                LIMIT 100
            """, (current_user.id, chat_id, chat_id, current_user.id))
        else:
            cur.execute("""
                SELECT gm.*, u.username as sender_name 
                FROM group_messages gm
                JOIN users u ON gm.sender_id = u.id
                WHERE gm.group_id = %s
                ORDER BY gm.timestamp DESC
                LIMIT 100
            """, (chat_id,))
        
        messages = cur.fetchall()
        return jsonify(messages)
    except Exception as e:
        print(f"Error fetching messages: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()


@app.route('/send_message', methods=['POST'])
@login_required
def send_message():
    try:
        data = request.get_json()
        chat_type = data.get('chat_type')
        chat_id = data.get('chat_id')
        message = data.get('message', '').strip()

        if not all([chat_type, chat_id, message]):
            return jsonify({'status': 'error', 'message': 'Неполные данные'}), 400

        cur = mysql.connection.cursor()

        if chat_type == 'user':
            # Проверка существования получателя
            cur.execute("SELECT 1 FROM users WHERE id = %s", (chat_id,))
            if not cur.fetchone():
                return jsonify({'status': 'error', 'message': 'Пользователь не найден'}), 404
            
            cur.execute("""
                INSERT INTO messages (sender_id, receiver_id, message)
                VALUES (%s, %s, %s)
            """, (current_user.id, chat_id, message))
        else:
            # Проверка членства в группе
            cur.execute("""
                SELECT 1 FROM group_members 
                WHERE group_id = %s AND user_id = %s
            """, (chat_id, current_user.id))
            if not cur.fetchone():
                return jsonify({'status': 'error', 'message': 'Вы не в группе'}), 403
            
            cur.execute("""
                INSERT INTO group_messages (group_id, sender_id, message)
                VALUES (%s, %s, %s)
            """, (chat_id, current_user.id, message))
        
        mysql.connection.commit()
        return jsonify({'status': 'success'}), 200
        
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if 'cur' in locals():
            cur.close()

@app.route('/create_group', methods=['GET'])
@login_required
def show_create_group():
    return render_template('create_group.html')

@app.route('/create_group', methods=['POST'])
@login_required
def create_group():
    name = request.form.get('name')
    description = request.form.get('description')
    
    if not name:
        flash('Group name is required', 'danger')
        return redirect(url_for('show_create_group'))
    
    cur = mysql.connection.cursor()
    try:
        cur.execute("INSERT INTO `chat_groups` (name, description, created_by) VALUES (%s, %s, %s)", 
                   (name, description, current_user.id))
        group_id = cur.lastrowid
        cur.execute("INSERT INTO group_members (group_id, user_id) VALUES (%s, %s)", 
                   (group_id, current_user.id))
        mysql.connection.commit()
        flash('Group created successfully!', 'success')
        return redirect(url_for('group_chat', group_id=group_id))
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error creating group: {str(e)}', 'danger')
        return redirect(url_for('show_create_group'))
    finally:
        cur.close()

# Маршруты для друзей
@app.route('/send_friend_request/<int:user_id>')
@login_required
def send_friend_request(user_id):
    cur = mysql.connection.cursor()
    try:
        # Проверяем, не отправили ли уже запрос
        cur.execute("""
            SELECT 1 FROM friend_requests 
            WHERE sender_id = %s AND receiver_id = %s AND status = 'pending'
        """, (current_user.id, user_id))
        if cur.fetchone():
            flash('Запрос дружбы уже отправлен', 'warning')
            return redirect(url_for('contacts'))
        
        # Создаем запрос
        cur.execute("""
            INSERT INTO friend_requests (sender_id, receiver_id)
            VALUES (%s, %s)
        """, (current_user.id, user_id))
        
        # Создаем уведомление
        cur.execute("""
            INSERT INTO notifications (user_id, content, notification_type, related_id)
            VALUES (%s, %s, 'friend_request', %s)
        """, (user_id, f"{current_user.username} хочет добавить вас в друзья", cur.lastrowid))
        
        mysql.connection.commit()
        flash('Запрос дружбы отправлен', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Ошибка: {str(e)}', 'danger')
    finally:
        cur.close()
    return redirect(url_for('contacts'))

# Маршруты для групп
@app.route('/invite_to_group/<int:group_id>/<int:user_id>')
@login_required
def invite_to_group(group_id, user_id):
    cur = mysql.connection.cursor()
    try:
        # Проверяем права (только участники группы могут приглашать)
        cur.execute("""
            SELECT 1 FROM group_members 
            WHERE group_id = %s AND user_id = %s
        """, (group_id, current_user.id))
        if not cur.fetchone():
            flash('Вы не можете приглашать в эту группу', 'danger')
            return redirect(url_for('group_chat', group_id=group_id))
        
        # Проверяем, не отправили ли уже приглашение
        cur.execute("""
            SELECT 1 FROM group_invitations 
            WHERE group_id = %s AND receiver_id = %s AND status = 'pending'
        """, (group_id, user_id))
        if cur.fetchone():
            flash('Приглашение уже отправлено', 'warning')
            return redirect(url_for('group_chat', group_id=group_id))
        
        # Создаем приглашение
        cur.execute("""
            INSERT INTO group_invitations (group_id, sender_id, receiver_id)
            VALUES (%s, %s, %s)
        """, (group_id, current_user.id, user_id))
        
        # Создаем уведомление
        cur.execute("SELECT name FROM chat_groups WHERE id = %s", (group_id,))
        group_name = cur.fetchone()['name']
        
        cur.execute("""
            INSERT INTO notifications (user_id, content, notification_type, related_id)
            VALUES (%s, %s, 'group_invite', %s)
        """, (user_id, f"{current_user.username} приглашает вас в группу '{group_name}'", cur.lastrowid))
        
        mysql.connection.commit()
        flash('Приглашение отправлено', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Ошибка: {str(e)}', 'danger')
    finally:
        cur.close()
    return redirect(url_for('group_chat', group_id=group_id))




# Маршруты для уведомлений

# Обработка принятия/отклонения запросов
@app.route('/handle_request/<string:type>/<int:request_id>/<string:action>')
@login_required
def handle_request(type, request_id, action):
    cur = mysql.connection.cursor()
    try:
        if type == 'friend':
            # Обновляем статус запроса дружбы
            cur.execute("""
                UPDATE friend_requests 
                SET status = %s 
                WHERE id = %s AND receiver_id = %s
            """, (action, request_id, current_user.id))
            
            # Если приняли - добавляем в друзья (ваша логика)
            if action == 'accepted':
                # Здесь можно добавить логику добавления в друзья
                pass
                
        elif type == 'group':
            # Обновляем статус приглашения в группу
            cur.execute("""
                UPDATE group_invitations 
                SET status = %s 
                WHERE id = %s AND receiver_id = %s
            """, (action, request_id, current_user.id))
            
            # Если приняли - добавляем в группу
            if action == 'accepted':
                cur.execute("""
                    SELECT group_id FROM group_invitations 
                    WHERE id = %s
                """, (request_id,))
                group_id = cur.fetchone()['group_id']
                
                cur.execute("""
                    INSERT INTO group_members (group_id, user_id)
                    VALUES (%s, %s)
                """, (group_id, current_user.id))
        
        mysql.connection.commit()
        flash(f'Запрос {action}', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Ошибка: {str(e)}', 'danger')
    finally:
        cur.close()
    return redirect(url_for('notifications'))

@app.route('/search_users')
@login_required
def search_users():
    query = request.args.get('q', '')
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT id, username FROM users 
        WHERE username LIKE %s AND id != %s
        LIMIT 10
    """, (f"%{query}%", current_user.id))
    users = cur.fetchall()
    cur.close()
    return jsonify(users)

@app.route('/join_group/<int:group_id>')
@login_required
def join_group(group_id):
    cur = mysql.connection.cursor()
    try:
        cur.execute("INSERT INTO group_members (group_id, user_id) VALUES (%s, %s)", 
                   (group_id, current_user.id))
        mysql.connection.commit()
        flash('You have joined the group!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error joining group: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('groups'))

@app.route('/group_chat/<int:group_id>')
@login_required
def group_chat(group_id):
    cur = mysql.connection.cursor()
    
    # Проверяем, является ли пользователь участником группы
    cur.execute("""
        SELECT 1 FROM group_members 
        WHERE group_id = %s AND user_id = %s
    """, (group_id, current_user.id))
    if not cur.fetchone():
        flash('You are not a member of this group', 'danger')
        return redirect(url_for('groups'))
    
    # Информация о группе (с исправленным названием таблицы)
    cur.execute("""
        SELECT g.*, u.username as creator_name 
        FROM chat_groups g
        JOIN users u ON g.created_by = u.id
        WHERE g.id = %s
    """, (group_id,))
    group = cur.fetchone()
    
    # Участники группы
    cur.execute("""
        SELECT u.id, u.username 
        FROM group_members gm
        JOIN users u ON gm.user_id = u.id
        WHERE gm.group_id = %s
    """, (group_id,))
    members = cur.fetchall()
    
    # Сообщения в группе
    cur.execute("""
        SELECT gm.*, u.username as sender_name 
        FROM group_messages gm
        JOIN users u ON gm.sender_id = u.id
        WHERE gm.group_id = %s
        ORDER BY gm.timestamp DESC
        LIMIT 50
    """, (group_id,))
    messages = cur.fetchall()
    cur.close()
    
    return render_template('group_chat.html', group=group, members=members, messages=messages)

@app.route('/profile')
@login_required
def profile():
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (current_user.id,))
    user_data = cur.fetchone()
    cur.close()
    
    return render_template('profile.html', user=user_data)


@app.route('/send_group_message', methods=['POST'])
@login_required
def send_group_message():
    group_id = request.form.get('group_id')
    message = request.form.get('message')
    
    if not group_id or not message:
        flash('Invalid request', 'danger')
        return redirect(url_for('groups'))
    
    try:
        group_id = int(group_id)
    except ValueError:
        flash('Invalid group', 'danger')
        return redirect(url_for('groups'))
    
    cur = mysql.connection.cursor()
    try:
        # Проверяем, является ли пользователь участником группы
        cur.execute("SELECT 1 FROM group_members WHERE group_id = %s AND user_id = %s", 
                   (group_id, current_user.id))
        if not cur.fetchone():
            flash('You are not a member of this group', 'danger')
            return redirect(url_for('groups'))
        
        cur.execute("""
            INSERT INTO group_messages (group_id, sender_id, message) 
            VALUES (%s, %s, %s)
        """, (group_id, current_user.id, message))
        mysql.connection.commit()
        flash('Message sent to group!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error sending message: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('group_chat', group_id=group_id))
    
    return redirect(url_for('chat'))


@app.route('/create_chat', methods=['POST'])
@login_required
def create_chat():
    chat_type = request.form.get('chatType')
    
    if chat_type == 'private':
        user_id = request.form.get('userId')
        # Логика создания личного чата
        return redirect(url_for('chat', user_id=user_id))
    else:
        group_name = request.form.get('groupName')
        members = request.form.getlist('members')
        # Логика создания группового чата
        return redirect(url_for('group_chat', group_id=new_group_id))



if __name__ == '__main__':
    app.run(debug=True)