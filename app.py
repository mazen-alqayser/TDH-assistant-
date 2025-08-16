from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, g, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import secrets
import google.generativeai as genai

# ====================
# تهيئة التطبيق
# ====================
app = Flask(__name__)
app.secret_key = "secret_key_for_session" # يفضل استخدام secrets.token_hex() في بيئة الإنتاج
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///tdh.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = "static/profile_pics"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024 # 16 ميغابايت كحد أقصى

# التأكد من وجود مجلد رفع الصور
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db = SQLAlchemy(app)

# ====================
# تهيئة Gemini AI
# ====================
API_KEY = "AIzaSyClaPw9XKcffyk3vGzSrGRCtlS_HoVlNVk" # تأكد من أن هذا المفتاح صحيح
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel(model_name="models/gemini-1.5-flash")

# ====================
# النماذج (تم التحديث)
# ====================
class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True) # تم تحديثه
    password = db.Column(db.String(120), nullable=False)
    training_course = db.Column(db.String(120), nullable=True)
    profile_picture = db.Column(db.String(255), nullable=True, default='default.png')
    bio = db.Column(db.Text, nullable=True, default="لا يوجد وصف شخصي حتى الآن.")
    
    # حقول جديدة لخاصية المشرف ووضع الحساب
    status = db.Column(db.String(20), default='pending', nullable=False) # 'pending', 'approved', 'rejected'
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    @property
    def profile_pic_url(self):
        if self.profile_picture:
            return url_for('static', filename=f'profile_pics/{self.profile_picture}')
        return url_for('static', filename='profile_pics/default.png')
    
class Post(db.Model):
    __tablename__ = "posts"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
    likes = db.Column(db.Integer, default=0)
    user = db.relationship("User", backref="posts")

class Comment(db.Model):
    __tablename__ = "comments"
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
    user = db.relationship("User")
    post = db.relationship("Post", backref="comments")

class Like(db.Model):
    __tablename__ = "likes"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='_user_post_uc'),)

class Center(db.Model):
    __tablename__ = "centers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(100), nullable=False)

class Announcement(db.Model):
    __tablename__ = "announcements"
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    admin = db.relationship('User', backref=db.backref('announcements', lazy='dynamic'))

# ====================
# الدوال المساعدة (تم التحديث)
# ====================
def get_current_user():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            return user
        else:
            session.pop('user_id', None)
    return None

def save_profile_picture(file):
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(file_path)
    return filename

# ====================
# جعل المستخدم الحالي متاحًا لجميع القوالب
# ====================
def login_required(f):
    def wrapper(*args, **kwargs):
        if not g.user:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

def is_admin(f):
    def wrapper(*args, **kwargs):
        if not g.is_admin:
            flash("ليس لديك صلاحية الوصول لهذه الصفحة.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

@app.before_request
def before_request():
    g.user = get_current_user()
    g.is_admin = g.user and g.user.is_admin
    
@app.context_processor
def inject_user():
    return dict(current_user=g.user, is_admin=g.is_admin)

# ====================
# المسارات (Routes)
# ====================
@app.route("/")
def index():
    if not g.user:
        return redirect(url_for("login"))
    
    if g.user and g.user.status == 'pending':
        return redirect(url_for('pending_approval'))
    
    posts = Post.query.order_by(Post.timestamp.desc()).all()
    liked_post_ids = {like.post_id for like in Like.query.filter_by(user_id=g.user.id).all()}
    
    return render_template("index.html", posts=posts, liked_post_ids=liked_post_ids)

@app.route("/intro")
def intro():
    if not g.user:
        return redirect(url_for("login"))
    if g.user.status == 'pending' and not g.is_admin:
        return redirect(url_for('pending_approval'))
    return render_template("intro.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        confirm = request.form.get("confirm")
        email = request.form.get("email") # تم إضافة حقل الإيميل
        
        if password != confirm:
            flash("كلمتا المرور غير متطابقتين", "warning")
            return redirect(url_for("register"))
        if User.query.filter_by(username=username).first():
            flash("اسم المستخدم موجود بالفعل", "warning")
            return redirect(url_for("register"))
        
        # استخدام التشفير لكلمة المرور
        hashed_password = generate_password_hash(password)
        user = User(username=username, email=email, password=hashed_password, status='pending')
        db.session.add(user)
        db.session.commit()
        
        flash("تم تسجيل حسابك بنجاح. سيتم مراجعته قريباً.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        if g.is_admin:
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for("index"))
        
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['is_admin'] = user.is_admin
            
            if user.is_admin:
                flash("مرحباً بك أيها المشرف!", "success")
                return redirect(url_for("admin_dashboard"))
            elif user.status == 'approved':
                flash("تم تسجيل الدخول بنجاح", "success")
                return redirect(url_for("index"))
            else:
                flash("حسابك قيد المراجعة حاليًا. يرجى الانتظار للموافقة.", "info")
                return redirect(url_for('pending_approval'))
        else:
            flash("اسم المستخدم أو كلمة المرور غير صحيحة.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("تم تسجيل الخروج", "success")
    return redirect(url_for("login"))

# مسار جديد لصفحة الانتظار
@app.route("/pending_approval")
def pending_approval():
    if g.is_admin:
        return redirect(url_for('admin_dashboard'))
    return render_template("pending_approval.html") # ستحتاج لإنشاء هذا الملف

@app.route("/admin")
@is_admin
def admin_dashboard():
    pending_users = User.query.filter_by(status='pending').all()
    all_posts = Post.query.order_by(Post.timestamp.desc()).all()
    centers = Center.query.all()
    announcements = Announcement.query.order_by(Announcement.timestamp.desc()).all()
    
    return render_template("admin_dashboard.html",
                           pending_users=pending_users,
                           all_posts=all_posts,
                           centers=centers,
                           announcements=announcements)

@app.route("/admin/approve_user/<int:user_id>", methods=["POST"])
@is_admin
def approve_user(user_id):
    user = User.query.get_or_404(user_id)
    user.status = 'approved'
    db.session.commit()
    flash(f"تمت الموافقة على حساب {user.username}.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route("/admin/reject_user/<int:user_id>", methods=["POST"])
@is_admin
def reject_user(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash(f"تم حذف حساب {user.username} ورفض طلبه.", "info")
    return redirect(url_for('admin_dashboard'))

@app.route("/admin/add_center", methods=["POST"])
@is_admin
def add_center():
    name = request.form.get("name")
    description = request.form.get("description")
    location = request.form.get("location")
    
    new_center = Center(name=name, description=description, location=location)
    db.session.add(new_center)
    db.session.commit()
    flash("تم إضافة المركز بنجاح.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route("/admin/delete_center/<int:center_id>", methods=["POST"])
@is_admin
def delete_center(center_id):
    center = Center.query.get_or_404(center_id)
    db.session.delete(center)
    db.session.commit()
    flash("تم حذف المركز بنجاح.", "info")
    return redirect(url_for('admin_dashboard'))

@app.route("/admin/delete_post/<int:post_id>", methods=["POST"])
@is_admin
def admin_delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    Comment.query.filter_by(post_id=post.id).delete()
    Like.query.filter_by(post_id=post.id).delete()
    db.session.delete(post)
    db.session.commit()
    flash("تم حذف المنشور وجميع تعليقاته.", "info")
    return redirect(url_for('admin_dashboard'))

# إضافة دالة admin_reply_post لمعالجة الردود
@app.route("/admin/reply_post/<int:post_id>", methods=["POST"])
@is_admin
def admin_reply_post(post_id):
    post = Post.query.get_or_404(post_id)
    reply_content = request.form.get("reply_content", "").strip()
    
    if not reply_content:
        flash("لا يمكن إرسال رد فارغ.", "warning")
        return redirect(url_for('admin_dashboard'))
    
    # إنشاء تعليق جديد باسم المشرف
    new_comment = Comment(
        post_id=post.id,
        user_id=g.user.id,
        content=reply_content
    )
    db.session.add(new_comment)
    db.session.commit()
    
    flash("تم إرسال الرد بنجاح!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route("/admin/publish_announcement", methods=["POST"])
@is_admin
def publish_announcement():
    content = request.form.get("content")
    if not content:
        flash("محتوى الإعلان فارغ.", "warning")
        return redirect(url_for('admin_dashboard'))
    
    new_announcement = Announcement(content=content, admin_id=g.user.id)
    db.session.add(new_announcement)
    db.session.commit()
    flash("تم نشر الإعلان بنجاح.", "success")
    return redirect(url_for('admin_dashboard'))
    
@app.route("/post_question", methods=["POST"])
@login_required
def post_question():
    if g.user.status != 'approved':
        abort(403) # يمنع النشر إذا لم يكن الحساب معتمدًا
    content = request.form.get("content").strip()
    if content:
        post = Post(user_id=g.user.id, content=content)
        db.session.add(post)
        db.session.commit()
        flash("تم نشر سؤالك بنجاح!", "success")
    return redirect(url_for("index"))

@app.route("/like/<int:post_id>", methods=["POST"])
@login_required
def like(post_id):
    if g.user.status != 'approved':
        return jsonify({"error": "غير مسموح"}), 403
    post = Post.query.get_or_404(post_id)
    like = Like.query.filter_by(user_id=g.user.id, post_id=post_id).first()
    if like:
        db.session.delete(like)
        post.likes = max(post.likes - 1, 0)
        liked = False
    else:
        new_like = Like(user_id=g.user.id, post_id=post_id)
        db.session.add(new_like)
        post.likes += 1
        liked = True
    db.session.commit()
    return jsonify({"likes": post.likes, "liked": liked})

@app.route("/comment/<int:post_id>", methods=["POST"])
@login_required
def comment_post(post_id):
    if g.user.status != 'approved':
        abort(403)
    content = request.form.get("content").strip()
    if content:
        comment = Comment(post_id=post_id, user_id=g.user.id, content=content)
        db.session.add(comment)
        db.session.commit()
        flash("تم إضافة تعليقك!", "success")
    return redirect(url_for("index"))

@app.route("/profile", methods=["GET", "POST"])
@login_required
def my_profile():
    if request.method == "POST":
        if "update_bio" in request.form:
            g.user.bio = request.form.get("bio", "").strip()
            db.session.commit()
            flash("تم تحديث الوصف الشخصي", "success")
        elif "profile_picture" in request.files:
            file = request.files["profile_picture"]
            if file and file.filename != "":
                filename = save_profile_picture(file)
                g.user.profile_picture = filename
                db.session.commit()
                flash("تم تحديث صورة الملف الشخصي", "success")
        elif "delete_account" in request.form:
            # حذف جميع البيانات المرتبطة بالمستخدم
            Post.query.filter_by(user_id=g.user.id).delete()
            Comment.query.filter_by(user_id=g.user.id).delete()
            Like.query.filter_by(user_id=g.user.id).delete()
            db.session.delete(g.user)
            db.session.commit()
            session.clear()
            flash("تم حذف الحساب بنجاح", "success")
            return redirect(url_for("register"))
            
    user_posts = Post.query.filter_by(user_id=g.user.id).order_by(Post.timestamp.desc()).all()
    return render_template("profile.html", user_posts=user_posts, user=g.user)

@app.route("/profile/<int:user_id>")
@login_required
def user_profile(user_id):
    user = User.query.get_or_404(user_id)
    user_posts = Post.query.filter_by(user_id=user.id).order_by(Post.timestamp.desc()).all()
    return render_template("user_profile.html", user=user, user_posts=user_posts)

@app.route("/ask_tdh_ai")
@login_required
def ask_tdh_ai():
    return render_template("ask_tdh_ai.html")

@app.route("/api/ask", methods=["POST"])
def ask_api():
    if not g.user:
        return jsonify({"error": "غير مصرح لك"}), 403
        
    data = request.get_json()
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"answer": "❌ الرجاء كتابة سؤال أولاً."})
    try:
        response = model.generate_content(question)
        answer = response.text.strip()
        return jsonify({"answer": answer})
    except Exception as e:
        print(f"خطأ أثناء الاتصال بـ TDH AI: {e}")
        return jsonify({"answer": "⚠️ حدث خطأ أثناء معالجة الطلب. الرجاء المحاولة لاحقًا."})

@app.route("/centers")
@login_required
def centers():
    centers_list = Center.query.all()
    return render_template("centers.html", centers=centers_list)

@app.route("/delete_post/<int:post_id>", methods=["POST"])
@login_required
def delete_post(post_id):
    if g.user.status != 'approved':
        return jsonify({"error": "غير مصرح لك"}), 403
    
    post = Post.query.get_or_404(post_id)
    if post.user_id != g.user.id:
        flash("لا يمكنك حذف منشور ليس منشورك", "danger")
        return redirect(url_for("index"))
    
    Comment.query.filter_by(post_id=post_id).delete()
    Like.query.filter_by(post_id=post_id).delete()
    
    db.session.delete(post)
    db.session.commit()
    flash("تم حذف المنشور", "success")
    return redirect(url_for("index"))


# ====================
# تشغيل التطبيق
# ====================

@app.cli.command("create-db")
def create_db():
    """ينشئ جداول قاعدة البيانات وحساب المشرف الأولي."""
    with app.app_context():
        db.create_all()
        print("تم إنشاء جداول قاعدة البيانات بنجاح.")
        
        # إنشاء حساب المشرف الأولي إذا لم يكن موجودًا
        admin_username = 'tdh_admin'
        admin_password = 'your_strong_admin_password_here' # **مهم: قم بتغيير كلمة المرور هذه**
        
        admin_user = User.query.filter_by(username=admin_username, is_admin=True).first()
        if not admin_user:
            hashed_password = generate_password_hash(admin_password)
            new_admin = User(
                username=admin_username, 
                email='admin@tdh.org', 
                password=hashed_password,
                status='approved',
                is_admin=True
            )
            db.session.add(new_admin)
            db.session.commit()
            print(f"تم إنشاء حساب المشرف بنجاح! اسم المستخدم: {admin_username} وكلمة المرور: {admin_password}")
        else:
            print("حساب المشرف موجود بالفعل. لم يتم إنشاء حساب جديد.")


if __name__ == "__main__":
    with app.app_context():
        # تأكد من أن قاعدة البيانات موجودة عند تشغيل التطبيق
        db.create_all()
        
    app.run(debug=True)
