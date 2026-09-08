import os
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'farzi_secret_key_2026'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# --- DATABASE CONFIGURATION ---
db_url = os.environ.get('DATABASE_URL', 'sqlite:///recycling.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- EMAIL HELPER ---
MAIL_SERVER = 'smtp.gmail.com'
MAIL_PORT = 587
MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')

def send_email_notification(to_email, subject, body):
    if not MAIL_USERNAME or not MAIL_PASSWORD:
        print("Email credentials not configured.")
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = MAIL_USERNAME
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(MAIL_SERVER, MAIL_PORT)
        server.starttls()
        server.login(MAIL_USERNAME, MAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

# --- DATABASE MODELS ---

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='volunteer')
    assigned_day = db.Column(db.String(20), nullable=True)
    submanager_job_done = db.Column(db.Boolean, default=False)
    points = db.Column(db.Integer, default=0)
    shifts = db.relationship('Shift', backref='volunteer', lazy=True, cascade='all, delete-orphan')
    comments = db.relationship('Feedback', backref='volunteer', lazy=True, cascade='all, delete-orphan')

class Shift(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    week_number = db.Column(db.Integer, nullable=False)
    day_name = db.Column(db.String(50), nullable=False)
    shift_time = db.Column(db.String(50), nullable=False)
    excused = db.Column(db.Boolean, default=False)
    excuse_reason = db.Column(db.String(255), nullable=True)
    attended = db.Column(db.Boolean, default=False)
    volunteer_job_done = db.Column(db.Boolean, default=False)

class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    submanager_name = db.Column(db.String(80), nullable=False)
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Metric(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(20), unique=True, nullable=False)
    count = db.Column(db.Integer, default=0)

class ImpactLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    logged_by = db.Column(db.String(80), nullable=False)
    bottles_collected = db.Column(db.Integer, default=0)
    weight_kg = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Notice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    author_name = db.Column(db.String(80), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

def get_unexcused_absences(user_id):
    return Shift.query.filter_by(user_id=user_id, attended=False, excused=False).count()

def calculate_user_badge(attended_shifts, points):
    if attended_shifts >= 15 or points >= 150:
        return {"title": "Eco Warrior", "icon": "🥇"}
    elif attended_shifts >= 8 or points >= 80:
        return {"title": "Recycling Champion", "icon": "🥈"}
    elif attended_shifts >= 3 or points >= 30:
        return {"title": "Green Contributor", "icon": "🥉"}
    return {"title": "Rookie Recycler", "icon": "🌱"}

# --- SAFE SCHEMA MIGRATION ---
def auto_migrate_db():
    db.create_all()
    user_cols = [
        ("assigned_day", "VARCHAR(20)"),
        ("submanager_job_done", "BOOLEAN DEFAULT FALSE"),
        ("email", "VARCHAR(120)"),
        ("points", "INTEGER DEFAULT 0")
    ]
    shift_cols = [
        ("excused", "BOOLEAN DEFAULT FALSE"),
        ("excuse_reason", "VARCHAR(255)"),
        ("attended", "BOOLEAN DEFAULT FALSE"),
        ("volunteer_job_done", "BOOLEAN DEFAULT FALSE")
    ]

    with db.engine.connect() as conn:
        for col, col_type in user_cols:
            try:
                conn.execute(text(f'ALTER TABLE "user" ADD COLUMN {col} {col_type};'))
                conn.commit()
            except Exception:
                pass

        for col, col_type in shift_cols:
            try:
                conn.execute(text(f'ALTER TABLE shift ADD COLUMN {col} {col_type};'))
                conn.commit()
            except Exception:
                pass

# --- GLOBAL BELL NOTIFICATION INJECTOR ---
@app.context_processor
def inject_notifications():
    if session.get('user_id'):
        latest_notices = Notice.query.order_by(Notice.created_at.desc()).limit(5).all()
        return dict(notifications=latest_notices, unread_count=len(latest_notices))
    return dict(notifications=[], unread_count=0)

# --- ROUTES ---

@app.route('/')
def home():
    all_users = User.query.order_by(User.full_name.asc()).all()
    total_bottles = db.session.query(db.func.sum(ImpactLog.bottles_collected)).scalar() or 0
    total_weight = db.session.query(db.func.sum(ImpactLog.weight_kg)).scalar() or 0.0
    co2_saved_kg = round(total_weight * 1.5, 2)
    leaderboard = User.query.filter_by(role='volunteer').order_by(User.points.desc()).limit(5).all()
    
    return render_template(
        'home.html', 
        users=all_users, 
        total_bottles=total_bottles, 
        total_weight=total_weight, 
        co2_saved_kg=co2_saved_kg,
        leaderboard=leaderboard
    )

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            session.permanent = True
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash(f"Welcome back, {user.full_name}!", "success")
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user.role == 'sub_manager':
                return redirect(url_for('submanager_dashboard'))
            return redirect(url_for('volunteer_dashboard'))
        else:
            flash("Invalid username or password.", "error")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Successfully logged out.", "success")
    return redirect(url_for('home'))

# --- ADMIN MANAGEMENT & USER EDITING ---

@app.route('/admin/dashboard')
def admin_dashboard():
    if session.get('role') != 'admin':
        flash("Access restricted to Primary Manager.", "error")
        return redirect(url_for('login'))
        
    volunteers = User.query.filter_by(role='volunteer').all()
    sub_managers = User.query.filter_by(role='sub_manager').all()
    shifts = Shift.query.all()
    absence_data = {v.id: get_unexcused_absences(v.id) for v in volunteers}
    
    return render_template('dashboard_admin.html', volunteers=volunteers, sub_managers=sub_managers, shifts=shifts, absence_data=absence_data)

@app.route('/admin/edit_user/<int:user_id>', methods=['POST'])
def edit_user(user_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
        
    user = User.query.get_or_404(user_id)
    user.full_name = request.form.get('full_name', '').strip() or user.full_name
    user.email = request.form.get('email', '').strip() or user.email
    
    # Role Switching (Volunteer <-> Sub-Manager)
    new_role = request.form.get('role')
    if new_role in ['volunteer', 'sub_manager', 'admin']:
        user.role = new_role
        if new_role == 'sub_manager':
            user.assigned_day = request.form.get('assigned_day')
        else:
            user.assigned_day = None

    # Password Update
    new_password = request.form.get('new_password', '').strip()
    if new_password:
        user.password_hash = generate_password_hash(new_password)
        
    db.session.commit()
    flash(f"Successfully updated {user.full_name}'s account!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/add_user', methods=['POST'])
def add_user():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    username = request.form.get('username', '').strip()
    full_name = request.form.get('full_name', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'volunteer')
    assigned_day = request.form.get('assigned_day') if role == 'sub_manager' else None
    
    if User.query.filter_by(username=username).first():
        flash("Username already exists.", "error")
    else:
        new_user = User(
            username=username,
            full_name=full_name,
            email=email if email else None,
            password_hash=generate_password_hash(password),
            role=role,
            assigned_day=assigned_day
        )
        db.session.add(new_user)
        db.session.commit()
        flash(f"Account created for {full_name}!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    user = User.query.get_or_404(user_id)
    if user.username == 'Zakaria':
        flash("Cannot delete primary admin account.", "error")
        return redirect(url_for('admin_dashboard'))
    db.session.delete(user)
    db.session.commit()
    flash("Account deleted.", "success")
    return redirect(url_for('admin_dashboard'))

# --- AUTOMATED & CUSTOM SHIFT MANAGEMENT ---

@app.route('/admin/generate_schedule', methods=['POST'])
def generate_two_week_schedule():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
        
    volunteers = User.query.filter_by(role='volunteer').all()
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday']
    default_time = request.form.get('shift_time', '12:00 PM - 12:30 PM')
    
    shifts_created = 0
    for week in [1, 2]:
        for day in days:
            for v in volunteers:
                exists = Shift.query.filter_by(user_id=v.id, week_number=week, day_name=day).first()
                if not exists:
                    new_shift = Shift(
                        user_id=v.id,
                        week_number=week,
                        day_name=day,
                        shift_time=default_time
                    )
                    db.session.add(new_shift)
                    shifts_created += 1
                    
    db.session.commit()
    flash(f"Generated {shifts_created} shifts across 2 Weeks (Mon-Thu)!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/add_custom_shift', methods=['POST'])
def add_custom_shift():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
        
    volunteer_id = request.form.get('volunteer_id')
    custom_name = request.form.get('custom_name', 'Special Shift').strip()
    week_num = int(request.form.get('week_number', 1))
    day_name = request.form.get('day_name', 'Monday')
    shift_time = request.form.get('shift_time', 'Special Hours').strip()
    
    new_shift = Shift(
        user_id=volunteer_id,
        week_number=week_num,
        day_name=f"{day_name} ({custom_name})",
        shift_time=shift_time
    )
    db.session.add(new_shift)
    db.session.commit()
    flash(f"Custom shift '{custom_name}' assigned successfully!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_shift/<int:shift_id>', methods=['POST'])
def delete_shift(shift_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    shift = Shift.query.get_or_404(shift_id)
    db.session.delete(shift)
    db.session.commit()
    flash("Shift removed.", "success")
    return redirect(url_for('admin_dashboard'))

# --- SUB-MANAGER & IMPACT LOGGING ---

@app.route('/submanager/dashboard')
def submanager_dashboard():
    if session.get('role') != 'sub_manager':
        flash("Access restricted to Sub-Managers.", "error")
        return redirect(url_for('login'))
        
    submanager = User.query.get(session['user_id'])
    assigned_shifts = Shift.query.filter_by(day_name=submanager.assigned_day).all()
    volunteers = User.query.filter_by(role='volunteer').all()
    absence_data = {v.id: get_unexcused_absences(v.id) for v in volunteers}
    
    return render_template('dashboard_submanager.html', submanager=submanager, shifts=assigned_shifts, volunteers=volunteers, absence_data=absence_data)

@app.route('/submanager/log_impact', methods=['POST'])
def log_impact():
    if session.get('role') not in ['admin', 'sub_manager']:
        return redirect(url_for('login'))
        
    bottles = int(request.form.get('bottles', 0))
    weight = float(request.form.get('weight', 0.0))
    
    if bottles > 0 or weight > 0:
        log = ImpactLog(
            logged_by=session['username'],
            bottles_collected=bottles,
            weight_kg=weight
        )
        db.session.add(log)
        db.session.commit()
        flash("Impact analytics updated successfully!", "success")
        
    return redirect(request.referrer or url_for('submanager_dashboard'))

@app.route('/submanager/toggle_attendance/<int:shift_id>', methods=['POST'])
def toggle_attendance(shift_id):
    if session.get('role') not in ['admin', 'sub_manager']:
        return redirect(url_for('login'))
    shift = Shift.query.get_or_404(shift_id)
    shift.attended = not shift.attended
    
    # Award gamification points on attendance
    if shift.attended and shift.volunteer:
        shift.volunteer.points += 10
    elif not shift.attended and shift.volunteer and shift.volunteer.points >= 10:
        shift.volunteer.points -= 10
        
    db.session.commit()
    flash("Attendance and points updated.", "success")
    return redirect(request.referrer or url_for('submanager_dashboard'))

@app.route('/submanager/add_feedback/<int:user_id>', methods=['POST'])
def add_feedback(user_id):
    if session.get('role') not in ['admin', 'sub_manager']:
        return redirect(url_for('login'))
    comment_text = request.form.get('comment', '').strip()
    if comment_text:
        fb = Feedback(
            user_id=user_id,
            submanager_name=session['username'],
            comment=comment_text
        )
        db.session.add(fb)
        db.session.commit()
        flash("Feedback posted for volunteer.", "success")
    return redirect(request.referrer or url_for('submanager_dashboard'))

@app.route('/submanager/complete_job', methods=['POST'])
def submanager_complete_job():
    if session.get('role') != 'sub_manager':
        return redirect(url_for('login'))
    submanager = User.query.get(session['user_id'])
    submanager.submanager_job_done = not submanager.submanager_job_done
    db.session.commit()
    flash("Daily management job status updated.", "success")
    return redirect(url_for('submanager_dashboard'))

# --- VOLUNTEER DASHBOARD ---

@app.route('/volunteer/dashboard')
def volunteer_dashboard():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    shifts = Shift.query.filter_by(user_id=user.id).all()
    attended_count = Shift.query.filter_by(user_id=user.id, attended=True).count()
    badge = calculate_user_badge(attended_count, user.points)
    
    return render_template('dashboard_volunteer.html', user=user, shifts=shifts, badge=badge)

@app.route('/volunteer/complete_job/<int:shift_id>', methods=['POST'])
def volunteer_complete_job(shift_id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    shift = Shift.query.get_or_404(shift_id)
    if shift.user_id == session['user_id']:
        shift.volunteer_job_done = not shift.volunteer_job_done
        db.session.commit()
        flash("Job completion status updated!", "success")
    return redirect(url_for('volunteer_dashboard'))

@app.route('/volunteer/excuse/<int:shift_id>', methods=['POST'])
def submit_excuse(shift_id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    shift = Shift.query.get_or_404(shift_id)
    if shift.user_id == session['user_id']:
        shift.excused = True
        shift.excuse_reason = request.form.get('reason', 'No reason provided')
        db.session.commit()
        flash("Excuse submitted to management.", "success")
    return redirect(url_for('volunteer_dashboard'))

# --- NOTICEBOARD ---

@app.route('/noticeboard', methods=['GET', 'POST'])
def noticeboard():
    if 'user_id' not in session:
        flash("Please log in to view noticeboard.", "error")
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        msg = request.form.get('message', '').strip()
        if msg:
            n = Notice(author_name=session['username'], message=msg)
            db.session.add(n)
            db.session.commit()
            flash("Notice posted successfully!", "success")
            
    notices = Notice.query.order_by(Notice.created_at.desc()).all()
    return render_template('noticeboard.html', notices=notices)

# --- AUTOMATED CRON ENDPOINT ---

@app.route('/api/cron/send-reminders', methods=['GET', 'POST'])
def automated_daily_reminders():
    tomorrow = datetime.utcnow() + timedelta(days=1)
    tomorrow_day = tomorrow.strftime('%A')
    
    upcoming_shifts = Shift.query.filter_by(day_name=tomorrow_day, excused=False).all()
    sent_count = 0
    
    for shift in upcoming_shifts:
        volunteer = shift.volunteer
        if volunteer and volunteer.email:
            subject = "[FARZI] Reminder: Your Recycling Shift is Tomorrow!"
            body = f"Hi {volunteer.full_name},\n\nThis is a reminder that you have a FARZI recycling shift tomorrow ({shift.day_name}):\n\n- Time: {shift.shift_time}\n- Week: {shift.week_number}\n\nThank you for supporting our school campaign!\n- FARZI Management"
            if send_email_notification(volunteer.email, subject, body):
                sent_count += 1
                
    return jsonify({"status": "success", "day_checked": tomorrow_day, "emails_sent": sent_count}), 200

# --- INITIALIZATION ---

with app.app_context():
    auto_migrate_db()
    
    admin = User.query.filter_by(username='Zakaria').first()
    if not admin:
        admin = User(
            username='Zakaria',
            full_name='Zakaria (Project Manager)',
            password_hash=generate_password_hash('zakariaprojectmanager1'),
            role='admin'
        )
        db.session.add(admin)

    for cat in ['daily', 'weekly', 'monthly', 'yearly']:
        if not Metric.query.filter_by(category=cat).first():
            db.session.add(Metric(category=cat, count=0))
            
    db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)