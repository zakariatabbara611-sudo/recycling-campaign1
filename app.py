import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'default-dev-key-change-in-prod')

# Database Configuration
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL or 'sqlite:///farzi_recycling.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ---------------------------------------------------------------------------
# MODELS
# ---------------------------------------------------------------------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='volunteer')  # admin, sub_manager, volunteer
    assigned_day = db.Column(db.String(20), nullable=True)  # Monday, Tuesday, Wednesday, Thursday
    submanager_job_done = db.Column(db.Boolean, default=False)
    points = db.Column(db.Integer, default=0)

    shifts = db.relationship('Shift', backref='volunteer', lazy=True, foreign_keys='Shift.volunteer_id')
    comments = db.relationship('Comment', backref='volunteer', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Shift(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    volunteer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    week_number = db.Column(db.Integer, nullable=False, default=1)
    day_name = db.Column(db.String(20), nullable=False)  # Monday, Tuesday, etc. or Custom Event Name
    shift_time = db.Column(db.String(50), nullable=False, default='12:00 PM - 12:30 PM')
    attended = db.Column(db.Boolean, default=False)
    volunteer_job_done = db.Column(db.Boolean, default=False)
    excused = db.Column(db.Boolean, default=False)
    excuse_reason = db.Column(db.Text, nullable=True)


class ImpactLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bottles_collected = db.Column(db.Integer, default=0)
    weight_kg = db.Column(db.Float, default=0.0)
    logged_at = db.Column(db.DateTime, default=datetime.utcnow)


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    volunteer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    submanager_name = db.Column(db.String(100), nullable=False)
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Notice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    author_name = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# GLOBAL CONTEXT PROCESSOR (FOR NOTIFICATIONS BELL)
# ---------------------------------------------------------------------------

@app.context_processor
def inject_notifications():
    if session.get('user_id'):
        notifications = Notice.query.order_by(Notice.created_at.desc()).limit(5).all()
        return dict(notifications=notifications, unread_count=len(notifications))
    return dict(notifications=[], unread_count=0)


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@app.route('/')
def home():
    total_bottles = db.session.query(db.func.sum(ImpactLog.bottles_collected)).scalar() or 0
    total_weight = db.session.query(db.func.sum(ImpactLog.weight_kg)).scalar() or 0
    co2_saved = round(total_weight * 1.5, 2)

    leaderboard = User.query.filter_by(role='volunteer').order_by(User.points.desc()).limit(5).all()
    all_users = User.query.all()

    return render_template(
        'home.html',
        total_bottles=total_bottles,
        total_weight=round(total_weight, 2),
        co2_saved_kg=co2_saved,
        leaderboard=leaderboard,
        users=all_users
    )


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['role'] = user.role
            session['username'] = user.username
            flash(f"Welcome back, {user.full_name}!", "success")

            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user.role == 'sub_manager':
                return redirect(url_for('submanager_dashboard'))
            else:
                return redirect(url_for('volunteer_dashboard'))
        else:
            flash("Invalid username or password.", "error")

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for('login'))


# --- ADMIN DASHBOARD & ACTIONS ---

@app.route('/admin')
def admin_dashboard():
    if session.get('role') != 'admin':
        flash("Unauthorized access.", "error")
        return redirect(url_for('login'))

    volunteers = User.query.filter_by(role='volunteer').all()
    sub_managers = User.query.filter_by(role='sub_manager').all()
    shifts = Shift.query.order_by(Shift.week_number, Shift.id).all()

    absence_data = {}
    for v in volunteers:
        absences = Shift.query.filter_by(volunteer_id=v.id, attended=False, excused=False).count()
        absence_data[v.id] = absences

    return render_template(
        'dashboard_admin.html',
        volunteers=volunteers,
        sub_managers=sub_managers,
        shifts=shifts,
        absence_data=absence_data
    )


@app.route('/admin/add_user', methods=['POST'])
def add_user():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    username = request.form.get('username')
    full_name = request.form.get('full_name')
    email = request.form.get('email')
    password = request.form.get('password')
    role = request.form.get('role', 'volunteer')
    assigned_day = request.form.get('assigned_day')

    if User.query.filter_by(username=username).first():
        flash("Username already exists.", "error")
        return redirect(url_for('admin_dashboard'))

    new_user = User(
        username=username,
        full_name=full_name,
        email=email,
        role=role,
        assigned_day=assigned_day if role == 'sub_manager' else None
    )
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()

    flash(f"User {full_name} created successfully.", "success")
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/edit_user/<int:user_id>', methods=['POST'])
def edit_user(user_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    user = User.query.get_or_404(user_id)
    user.full_name = request.form.get('full_name')
    user.email = request.form.get('email')
    user.role = request.form.get('role')
    user.assigned_day = request.form.get('assigned_day') if user.role == 'sub_manager' else None

    new_password = request.form.get('new_password')
    if new_password and new_password.strip():
        user.set_password(new_password)

    db.session.commit()
    flash(f"Updated user account: {user.full_name}", "success")
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    user = User.query.get_or_404(user_id)
    if user.username == 'Zakaria':
        flash("Cannot delete primary admin account.", "error")
        return redirect(url_for('admin_dashboard'))

    # Unassign shifts and delete user
    Shift.query.filter_by(volunteer_id=user.id).update({'volunteer_id': None})
    Comment.query.filter_by(volunteer_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()

    flash("User account deleted.", "success")
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/generate_schedule', methods=['POST'])
def generate_two_week_schedule():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    shift_time = request.form.get('shift_time', '12:00 PM - 12:30 PM')
    volunteers = User.query.filter_by(role='volunteer').all()

    if not volunteers:
        flash("No volunteers found to generate schedule.", "error")
        return redirect(url_for('admin_dashboard'))

    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday']
    v_index = 0

    for week in [1, 2]:
        for day in days:
            assigned_v = volunteers[v_index % len(volunteers)]
            shift = Shift(
                volunteer_id=assigned_v.id,
                week_number=week,
                day_name=day,
                shift_time=shift_time
            )
            db.session.add(shift)
            v_index += 1

    db.session.commit()
    flash("2-Week Schedule generated successfully!", "success")
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/add_custom_shift', methods=['POST'])
def add_custom_shift():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    volunteer_id = request.form.get('volunteer_id')
    custom_name = request.form.get('custom_name')
    week_number = request.form.get('week_number', 1, type=int)
    day_name = request.form.get('day_name')
    shift_time = request.form.get('shift_time')

    shift = Shift(
        volunteer_id=volunteer_id,
        week_number=week_number,
        day_name=f"{day_name} ({custom_name})",
        shift_time=shift_time
    )
    db.session.add(shift)
    db.session.commit()

    flash("Custom shift assigned successfully.", "success")
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


# --- SUB-MANAGER DASHBOARD & ACTIONS ---

@app.route('/submanager')
def submanager_dashboard():
    if session.get('role') != 'sub_manager':
        flash("Unauthorized access.", "error")
        return redirect(url_for('login'))

    submanager = User.query.get(session['user_id'])
    shifts = Shift.query.filter_by(day_name=submanager.assigned_day).all()
    volunteers = User.query.filter_by(role='volunteer').all()

    absence_data = {}
    for v in volunteers:
        absences = Shift.query.filter_by(volunteer_id=v.id, attended=False, excused=False).count()
        absence_data[v.id] = absences

    return render_template(
        'dashboard_submanager.html',
        submanager=submanager,
        shifts=shifts,
        volunteers=volunteers,
        absence_data=absence_data
    )


@app.route('/submanager/complete_job', methods=['POST'])
def submanager_complete_job():
    if session.get('role') != 'sub_manager':
        return redirect(url_for('login'))

    submanager = User.query.get(session['user_id'])
    submanager.submanager_job_done = not submanager.submanager_job_done
    db.session.commit()

    flash("Supervision status updated.", "success")
    return redirect(url_for('submanager_dashboard'))


@app.route('/submanager/toggle_attendance/<int:shift_id>', methods=['POST'])
def toggle_attendance(shift_id):
    if session.get('role') != 'sub_manager':
        return redirect(url_for('login'))

    shift = Shift.query.get_or_404(shift_id)
    shift.attended = not shift.attended

    if shift.volunteer:
        if shift.attended:
            shift.volunteer.points += 10
        else:
            shift.volunteer.points = max(0, shift.volunteer.points - 10)

    db.session.commit()
    flash("Attendance updated.", "success")
    return redirect(url_for('submanager_dashboard'))


@app.route('/submanager/log_impact', methods=['POST'])
def log_impact():
    if session.get('role') not in ['sub_manager', 'admin']:
        return redirect(url_for('login'))

    bottles = request.form.get('bottles', 0, type=int)
    weight = request.form.get('weight', 0.0, type=float)

    if bottles > 0 or weight > 0:
        log = ImpactLog(bottles_collected=bottles, weight_kg=weight)
        db.session.add(log)
        db.session.commit()
        flash("Impact metrics logged successfully!", "success")
    else:
        flash("Please enter valid collection numbers.", "error")

    return redirect(request.referrer or url_for('submanager_dashboard'))


@app.route('/submanager/add_feedback/<int:user_id>', methods=['POST'])
def add_feedback(user_id):
    if session.get('role') != 'sub_manager':
        return redirect(url_for('login'))

    comment_text = request.form.get('comment')
    if comment_text:
        c = Comment(
            volunteer_id=user_id,
            submanager_name=session.get('username'),
            comment=comment_text
        )
        db.session.add(c)
        db.session.commit()
        flash("Feedback posted.", "success")

    return redirect(url_for('submanager_dashboard'))


# --- VOLUNTEER DASHBOARD & ACTIONS ---

@app.route('/volunteer')
def volunteer_dashboard():
    if session.get('role') != 'volunteer':
        flash("Unauthorized access.", "error")
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    shifts = Shift.query.filter_by(volunteer_id=user.id).order_by(Shift.week_number).all()

    # Calculate Badge
    badge = {"title": "Bronze Recycler", "icon": "🥉"}
    if user.points >= 50:
        badge = {"title": "Gold Recycler", "icon": "🥇"}
    elif user.points >= 20:
        badge = {"title": "Silver Recycler", "icon": "🥈"}

    return render_template(
        'dashboard_volunteer.html',
        user=user,
        shifts=shifts,
        badge=badge
    )


@app.route('/volunteer/complete_job/<int:shift_id>', methods=['POST'])
def volunteer_complete_job(shift_id):
    if session.get('role') != 'volunteer':
        return redirect(url_for('login'))

    shift = Shift.query.get_or_404(shift_id)
    if shift.volunteer_id == session.get('user_id'):
        shift.volunteer_job_done = not shift.volunteer_job_done
        db.session.commit()
        flash("Task status updated.", "success")

    return redirect(url_for('volunteer_dashboard'))


@app.route('/volunteer/submit_excuse/<int:shift_id>', methods=['POST'])
def submit_excuse(shift_id):
    if session.get('role') != 'volunteer':
        return redirect(url_for('login'))

    shift = Shift.query.get_or_404(shift_id)
    reason = request.form.get('reason')

    if shift.volunteer_id == session.get('user_id') and reason:
        shift.excused = True
        shift.excuse_reason = reason
        db.session.commit()
        flash("Excuse submitted.", "success")

    return redirect(url_for('volunteer_dashboard'))


# --- NOTICEBOARD ---

@app.route('/noticeboard', methods=['GET', 'POST'])
def noticeboard():
    if not session.get('user_id'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        message = request.form.get('message')
        if message:
            notice = Notice(
                author_name=session.get('username'),
                message=message
            )
            db.session.add(notice)
            db.session.commit()
            flash("Notice posted to board.", "success")

    notices = Notice.query.order_by(Notice.created_at.desc()).all()
    return render_template('noticeboard.html', notices=notices)


# ---------------------------------------------------------------------------
# DATABASE INITIALIZATION & MIGRATIONS
# ---------------------------------------------------------------------------

with app.app_context():
    # 1. Create missing tables
    db.create_all()

    # 2. Safely add missing columns to existing database tables
    try:
        db.session.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS points INTEGER DEFAULT 0;'))
        db.session.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS submanager_job_done BOOLEAN DEFAULT FALSE;'))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Migration Note: {e}")

    # 3. Create initial Admin account if it doesn't exist
    admin = User.query.filter_by(username='Zakaria').first()
    if not admin:
        admin = User(
            username='Zakaria',
            full_name='Zakaria Tabbara',
            email='admin@school.edu',
            role='admin'
        )
        admin.set_password('AdminPassword123')
        db.session.add(admin)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)