import os
import random
import string
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = "recycling_campaign_super_secret_key"
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Database Setup
db_url = os.environ.get('DATABASE_URL', 'sqlite:///recycling.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- DATABASE MODELS ---

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)

class Shift(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    volunteer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    week_number = db.Column(db.Integer, nullable=False)
    day_name = db.Column(db.String(20), nullable=False)
    shift_time = db.Column(db.String(50), nullable=False)
    excused = db.Column(db.Boolean, default=False)
    excuse_reason = db.Column(db.String(255), nullable=True)
    volunteer = db.relationship('User', backref='shifts')

class Metric(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(20), unique=True, nullable=False)
    count = db.Column(db.Integer, default=0)

class Notice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    author_name = db.Column(db.String(80), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# --- ROUTES ---

@app.route('/')
def home():
    metrics = {m.category: m.count for m in Metric.query.all()}
    return render_template('index.html', metrics=metrics)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        user = User.query.filter_by(username=username).first()
        if user and user.password == password:
            session.permanent = True
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash("Logged in successfully!", "success")
            
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('volunteer_dashboard'))
        else:
            flash("Invalid username or password.", "error")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for('home'))

@app.route('/volunteer/dashboard')
def volunteer_dashboard():
    if session.get('role') != 'volunteer':
        flash("Access restricted to volunteers.", "error")
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    shifts = Shift.query.filter_by(volunteer_id=user_id).all()
    
    tomorrow_alert = any(not s.excused for s in shifts)
            
    return render_template('dashboard_volunteer.html', shifts=shifts, tomorrow_alert=tomorrow_alert)

@app.route('/volunteer/excuse/<int:shift_id>', methods=['POST'])
def submit_excuse(shift_id):
    if session.get('role') != 'volunteer':
        return redirect(url_for('login'))
        
    shift = Shift.query.get_or_404(shift_id)
    if shift.volunteer_id == session['user_id']:
        shift.excused = True
        shift.excuse_reason = request.form.get('reason', 'No reason provided')
        db.session.commit()
        flash("Excuse submitted to management.", "success")
        
    return redirect(url_for('volunteer_dashboard'))

@app.route('/admin/dashboard', methods=['GET', 'POST'])
def admin_dashboard():
    if session.get('role') != 'admin':
        flash("Access restricted to managers.", "error")
        return redirect(url_for('login'))
        
    volunteers = User.query.filter_by(role='volunteer').all()
    managers = User.query.filter_by(role='admin').all()
    shifts = Shift.query.all()
    metrics = {m.category: m for m in Metric.query.all()}
    
    return render_template('dashboard_admin.html', volunteers=volunteers, managers=managers, shifts=shifts, metrics=metrics)

@app.route('/admin/add_user', methods=['POST'])
def add_user():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
        
    username = request.form.get('username').strip()
    full_name = request.form.get('full_name').strip()
    role = request.form.get('role')
    
    gen_pass = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    
    if not User.query.filter_by(username=username).first():
        new_u = User(username=username, password=gen_pass, role=role, full_name=full_name)
        db.session.add(new_u)
        db.session.commit()
        flash(f"Account created for {full_name}! Temp Password: {gen_pass}", "success")
    else:
        flash("Username already exists.", "error")
        
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/add_shift', methods=['POST'])
def add_shift():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
        
    vol_id = request.form.get('volunteer_id')
    week = request.form.get('week_number')
    day = request.form.get('day_name')
    time = request.form.get('shift_time')
    
    shift = Shift(volunteer_id=vol_id, week_number=week, day_name=day, shift_time=time)
    db.session.add(shift)
    db.session.commit()
    flash("Shift assigned successfully!", "success")
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/update_metrics', methods=['POST'])
def update_metrics():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
        
    for cat in ['daily', 'weekly', 'monthly', 'yearly']:
        val = request.form.get(cat)
        if val is not None and val.isdigit():
            m = Metric.query.filter_by(category=cat).first()
            if m:
                m.count = int(val)
                
    db.session.commit()
    flash("Bottle collection metrics updated!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/noticeboard', methods=['GET', 'POST'])
def noticeboard():
    if 'user_id' not in session:
        flash("Please log in to view the team noticeboard.", "error")
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        msg = request.form.get('message', '').strip()
        if msg:
            n = Notice(author_name=session['username'], message=msg)
            db.session.add(n)
            db.session.commit()
            flash("Notice posted!", "success")
            
    notices = Notice.query.order_by(Notice.created_at.desc()).all()
    return render_template('noticeboard.html', notices=notices)

# Initialization inside app context
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='Zakaria').first():
        admin = User(username='Zakaria', password='zakariaprojectmanager1', role='admin', full_name='Zakaria (Project Manager)')
        db.session.add(admin)
        
    for cat in ['daily', 'weekly', 'monthly', 'yearly']:
        if not Metric.query.filter_by(category=cat).first():
            db.session.add(Metric(category=cat, count=0))
            
    db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)