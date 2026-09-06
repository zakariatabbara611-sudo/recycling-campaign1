import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'farzi_secret_key_2026'

# Database Setup (Supports Render PostgreSQL or local SQLite fallback)
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
    full_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='volunteer')  # 'admin' or 'volunteer'
    shifts = db.relationship('Shift', backref='volunteer', lazy=True, cascade='all, delete-orphan')

class Shift(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    week_number = db.Column(db.Integer, nullable=False)
    day_name = db.Column(db.String(20), nullable=False)
    shift_time = db.Column(db.String(20), nullable=False)
    excused = db.Column(db.Boolean, default=False)
    excuse_reason = db.Column(db.String(255), nullable=True)

class Notice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=False)

# --- ROUTES ---

@app.route('/')
def home():
    all_users = User.query.order_by(User.full_name.asc()).all()
    return render_template('home.html', users=all_users)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash(f"Welcome back, {user.full_name}!", "success")
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('volunteer_dashboard'))
        else:
            flash("Invalid username or password.", "error")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Successfully logged out.", "success")
    return redirect(url_for('home'))

@app.route('/admin/dashboard')
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    volunteers = User.query.filter_by(role='volunteer').all()
    managers = User.query.filter_by(role='admin').all()
    shifts = Shift.query.all()
    return render_template('dashboard_admin.html', volunteers=volunteers, managers=managers, shifts=shifts)

@app.route('/admin/add_user', methods=['POST'])
def add_user():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    username = request.form.get('username', '').strip()
    full_name = request.form.get('full_name', '').strip()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'volunteer')
    
    if User.query.filter_by(username=username).first():
        flash("Username already exists.", "error")
    else:
        new_user = User(
            username=username,
            full_name=full_name,
            password_hash=generate_password_hash(password),
            role=role
        )
        db.session.add(new_user)
        db.session.commit()
        flash("Account created successfully!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    user = User.query.get_or_404(user_id)
    if user.username == 'Zakaria':
        flash("Cannot delete main admin account.", "error")
        return redirect(url_for('admin_dashboard'))
    db.session.delete(user)
    db.session.commit()
    flash("Account deleted.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/toggle_role/<int:user_id>', methods=['POST'])
def toggle_role(user_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    user = User.query.get_or_404(user_id)
    user.role = 'admin' if user.role == 'volunteer' else 'volunteer'
    db.session.commit()
    flash(f"Role updated for {user.full_name}.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/add_shift', methods=['POST'])
def add_shift():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    volunteer_id = request.form.get('volunteer_id')
    week_number = request.form.get('week_number')
    day_name = request.form.get('day_name')
    shift_time = request.form.get('shift_time')
    
    new_shift = Shift(
        user_id=volunteer_id,
        week_number=int(week_number),
        day_name=day_name,
        shift_time=shift_time
    )
    db.session.add(new_shift)
    db.session.commit()
    flash("Shift assigned.", "success")
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

@app.route('/volunteer/dashboard')
def volunteer_dashboard():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    return render_template('dashboard_volunteer.html', user=user)

@app.route('/volunteer/submit_excuse/<int:shift_id>', methods=['POST'])
def submit_excuse(shift_id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    shift = Shift.query.get_or_404(shift_id)
    if shift.user_id == session['user_id']:
        shift.excused = True
        shift.excuse_reason = request.form.get('reason')
        db.session.commit()
        flash("Excuse submitted.", "success")
    return redirect(url_for('volunteer_dashboard'))

@app.route('/noticeboard')
def noticeboard():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    notices = Notice.query.all()
    return render_template('noticeboard.html', notices=notices)

@app.route('/noticeboard/add', methods=['POST'])
def add_notice():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    title = request.form.get('title')
    content = request.form.get('content')
    new_notice = Notice(title=title, content=content)
    db.session.add(new_notice)
    db.session.commit()
    flash("Notice posted.", "success")
    return redirect(url_for('noticeboard'))

# Database Initialization & Admin Seeding
with app.app_context():
    db.create_all()
    admin_user = User.query.filter_by(username='Zakaria').first()
    if not admin_user:
        admin = User(
            username='Zakaria',
            full_name='Zakaria (Project Manager)',
            password_hash=generate_password_hash('zakariaprojectmanager1'),
            role='admin'
        )
        db.session.add(admin)
        db.session.commit()
    else:
        # Update existing user password hash to guarantee login works
        admin_user.password_hash = generate_password_hash('zakariaprojectmanager1')
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)