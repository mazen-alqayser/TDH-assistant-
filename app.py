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
# ⚠️ تم التعديل: يفضل استخدام متغيرات البيئة للمفاتيح السرية
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(24))
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///tdh.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = "static/profile_pics"
app.config["POST_IMAGES_FOLDER"] = "static/post_images"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 ميغابايت كحد أقصى

# التأكد من وجود مجلدات رفع الصور
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["POST_IMAGES_FOLDER"], exist_ok=True)

db = SQLAlchemy(app)

# ====================
# تهيئة Gemini AI
# ====================
# ⚠️ تم التعديل: استخدام المفتاح مباشرةً لضمان عمله
import google.generativeai as genai

# استبدل النص التالي بمفتاح API الخاص بك.
# ملاحظة: هذه الطريقة غير آمنة في بيئات الإنتاج.
# الطريقة الأفضل هي استخدام متغيرات البيئة.
genai.configure(api_key="AIzaSyBoe4Z2LespjBQ7d8d6iuroyjYgkR5PFY0")
model = genai.GenerativeModel(model_name="models/gemini-1.5-flash")

# ====================
# النماذج (تم التحديث)
class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password = db.Column(db.String(120), nullable=False)
    training_course = db.Column(db.String(120), nullable=True)
    profile_picture = db.Column(db.String(255), nullable=True, default='default.png')
    bio = db.Column(db.Text, nullable=True, default="لا يوجد وصف شخصي حتى الآن.")
    
    status = db.Column(db.String(20), default='pending', nullable=False)
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
    image_url = db.Column(db.String(255), nullable=True)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
    likes = db.Column(db.Integer, default=0)
    user = db.relationship("User", backref="posts")
    is_announcement = db.Column(db.Boolean, default=False, nullable=False)
    # ⚠️ تم التعديل: لإضافة علاقة Comments
    comments = db.relationship("Comment", backref="post", lazy=True, cascade="all, delete-orphan")
    # ⚠️ تم التعديل: لإضافة علاقة Likes
    likes_rel = db.relationship("Like", backref="post", lazy=True, cascade="all, delete-orphan")

class Comment(db.Model):
    __tablename__ = "comments"
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
    # ⚠️ تم التعديل: إضافة backref للمستخدم
    user = db.relationship("User", backref=db.backref("comments", lazy=True))

class Like(db.Model):
    __tablename__ = "likes"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='_user_post_uc'),)
    # ⚠️ تم التعديل: إضافة علاقة المستخدم
    user = db.relationship("User", backref=db.backref("likes", lazy=True))

class Center(db.Model):
    __tablename__ = "centers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(100), nullable=False)
    website = db.Column(db.String(255), nullable=True)

# ====================
# الدوال المساعدة
# ====================
def get_current_user():
    user_id = session.get('user_id')
    if user_id:
        return User.query.get(user_id)
    return None

def save_profile_picture(file):
    filename = secure_filename(file.filename)
    # ⚠️ تم التعديل: إضافة اسم ملف فريد
    unique_filename = f"{secrets.token_hex(8)}_{filename}"
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], unique_filename)
    file.save(file_path)
    return unique_filename

def save_post_image(file):
    filename = secure_filename(file.filename)
    unique_filename = f"{secrets.token_hex(8)}_{filename}"
    file_path = os.path.join(app.config["POST_IMAGES_FOLDER"], unique_filename)
    file.save(file_path)
    return unique_filename

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
@login_required
def index():
    if g.user.status == 'pending':
        return redirect(url_for('pending_approval'))
    
    posts = Post.query.order_by(Post.timestamp.desc()).all()
    liked_post_ids = {like.post_id for like in Like.query.filter_by(user_id=g.user.id).all()}
    
    return render_template("index.html", posts=posts, liked_post_ids=liked_post_ids)

@app.route("/intro")
@login_required
def intro():
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
        email = request.form.get("email")
        
        if password != confirm:
            flash("كلمتا المرور غير متطابقتين", "warning")
            return redirect(url_for("register"))
        if User.query.filter_by(username=username).first():
            flash("اسم المستخدم موجود بالفعل", "warning")
            return redirect(url_for("register"))
        
        hashed_password = generate_password_hash(password)
        user = User(username=username, email=email, password=hashed_password, status='pending')
        db.session.add(user)
        db.session.commit()
        
        flash("تم تسجيل حسابك بنجاح. سيتم مراجعته قريباً.", "success")
        
        # ⚠️ تم التعديل: لا تسجل الدخول تلقائياً، بل أرسل المستخدم إلى صفحة تسجيل الدخول ليعرف أنه يحتاج للموافقة
        return redirect(url_for('login'))
    return render_template("register.html")
@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        if g.user.is_admin:
            return redirect(url_for('admin_dashboard'))
        elif g.user.status == 'approved':
            return redirect(url_for("intro"))  # ⬅️ يدخل الانترو أولاً
        else:
            return redirect(url_for('pending_approval'))
    
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            if user.status == 'pending':
                flash("حسابك قيد المراجعة حاليًا. يرجى الانتظار للموافقة.", "info")
                return redirect(url_for('pending_approval'))
            
            session['user_id'] = user.id
            session['is_admin'] = user.is_admin
            
            flash("تم تسجيل الدخول بنجاح", "success")
            if user.is_admin:
                return redirect(url_for("admin_dashboard"))
            else:
                return redirect(url_for("intro"))  # ⬅️ تعديل هنا أيضًا
        else:
            flash("اسم المستخدم أو كلمة المرور غير صحيحة.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("تم تسجيل الخروج", "success")
    return redirect(url_for("login"))

@app.route("/pending_approval")
@login_required
def pending_approval():
    if g.user.status == 'approved' and not g.is_admin:
        return redirect(url_for('index'))
    if g.is_admin:
        return redirect(url_for('admin_dashboard'))
    return render_template("pending_approval.html")

@app.route("/admin")
@is_admin
@login_required
def admin_dashboard():
    pending_users = User.query.filter_by(status='pending').all()
    all_posts = Post.query.order_by(Post.timestamp.desc()).all()
    centers = Center.query.all()
    
    return render_template("admin_dashboard.html",
                           pending_users=pending_users,
                           all_posts=all_posts,
                           centers=centers)

@app.route("/admin/approve_user/<int:user_id>", methods=["POST"])
@is_admin
@login_required
def approve_user(user_id):
    user = User.query.get_or_404(user_id)
    user.status = 'approved'
    db.session.commit()
    flash(f"تمت الموافقة على حساب {user.username}.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route("/admin/reject_user/<int:user_id>", methods=["POST"])
@is_admin
@login_required
def reject_user(user_id):
    user = User.query.get_or_404(user_id)
    # ⚠️ تم التعديل: حذف البيانات المرتبطة أولاً
    Post.query.filter_by(user_id=user.id).delete()
    Comment.query.filter_by(user_id=user.id).delete()
    Like.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    flash(f"تم حذف حساب {user.username} ورفض طلبه.", "info")
    return redirect(url_for('admin_dashboard'))

@app.route("/admin/add_center", methods=["POST"])
@is_admin
@login_required
def add_center():
    name = request.form.get("name")
    description = request.form.get("description")
    location = request.form.get("location")
    website = request.form.get("website")
    
    if not all([name, description, location]):
        flash("يجب ملء جميع الحقول.", "warning")
        return redirect(url_for('admin_dashboard'))
    
    new_center = Center(name=name, description=description, location=location, website=website)
    db.session.add(new_center)
    db.session.commit()
    flash("تم إضافة المركز بنجاح.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route("/admin/delete_center/<int:center_id>", methods=["POST"])
@is_admin
@login_required
def delete_center(center_id):
    center = Center.query.get_or_404(center_id)
    db.session.delete(center)
    db.session.commit()
    flash("تم حذف المركز بنجاح.", "info")
    return redirect(url_for('admin_dashboard'))

@app.route("/admin/delete_post/<int:post_id>", methods=["POST"])
@is_admin
@login_required
def admin_delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.image_url:
        # ⚠️ تم التعديل: استخدام os.path.basename
        filename = os.path.basename(post.image_url)
        image_path = os.path.join(app.config['POST_IMAGES_FOLDER'], filename)
        if os.path.exists(image_path):
            os.remove(image_path)
    
    # ⚠️ تم التعديل: حذف البيانات المرتبطة أولاً
    Comment.query.filter_by(post_id=post.id).delete()
    Like.query.filter_by(post_id=post.id).delete()
    db.session.delete(post)
    db.session.commit()
    flash("تم حذف المنشور وجميع تعليقاته.", "info")
    return redirect(url_for('admin_dashboard'))

@app.route("/admin/reply_post/<int:post_id>", methods=["POST"])
@is_admin
@login_required
def admin_reply_post(post_id):
    post = Post.query.get_or_404(post_id)
    reply_content = request.form.get("reply_content", "").strip()
    
    if not reply_content:
        flash("لا يمكن إرسال رد فارغ.", "warning")
        return redirect(url_for('admin_dashboard'))
    
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
@login_required
def publish_announcement():
    content = request.form.get("content").strip()
    image_file = request.files.get("announcement_image")
    image_url = None
    
    if not content and not image_file:
        flash("لا يمكن نشر إعلان فارغ.", "warning")
        return redirect(url_for('admin_dashboard'))
    
    if image_file and image_file.filename and allowed_file(image_file.filename):
        filename = save_post_image(image_file)
        image_url = url_for('static', filename=f'post_images/{filename}')
    
    new_announcement_post = Post(
        user_id=g.user.id,
        content=content,
        image_url=image_url,
        is_announcement=True
    )
    db.session.add(new_announcement_post)
    db.session.commit()
    
    flash("تم نشر الإعلان بنجاح.", "success")
    return redirect(url_for('admin_dashboard'))
    
@app.route("/post_question", methods=["POST"])
@login_required
def post_question():
    if g.user.status != 'approved':
        abort(403)
    content = request.form.get("content", "").strip()
    image = request.files.get('image')
    image_url = None
    
    if image and image.filename and allowed_file(image.filename):
        filename = save_post_image(image)
        image_url = url_for('static', filename=f'post_images/{filename}')
    
    if content or image_url:
        post = Post(user_id=g.user.id, content=content, image_url=image_url)
        db.session.add(post)
        db.session.commit()
        flash("تم نشر سؤالك/منشورك بنجاح!", "success")
    else:
        flash("لا يمكن نشر محتوى فارغ.", "warning")
    return redirect(url_for("index"))

@app.route("/like/<int:post_id>", methods=["POST"])
@login_required
def like(post_id):
    if g.user.status != 'approved':
        return jsonify({"success": False, "message": "غير مسموح"}), 403
    
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
    
    return jsonify({"success": True, "likes": post.likes, "liked": liked})

@app.route("/comment/<int:post_id>", methods=["POST"])
@login_required
def comment_post(post_id):
    if g.user.status != 'approved':
        flash("⚠️ غير مصرح لك بالتعليق", "danger")
        return redirect(url_for("view_post", post_id=post_id))

    # الحصول على البيانات من الـ form
    content = request.form.get("content", "").strip()

    if not content:
        flash("⚠️ لا يمكن إضافة تعليق فارغ", "warning")
        return redirect(url_for("view_post", post_id=post_id))
    
    post = Post.query.get_or_404(post_id)
    
    new_comment = Comment(post_id=post_id, user_id=g.user.id, content=content)
    db.session.add(new_comment)
    db.session.commit()

    flash("✅ تم إضافة تعليقك بنجاح", "success")
    return redirect(url_for("view_post", post_id=post_id))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def my_profile():
    if request.method == "POST":
        if 'update_profile_button' in request.form:
            g.user.bio = request.form.get('bio', '').strip()
            g.user.training_course = request.form.get('training_course', '').strip()
            
            if 'profile_picture' in request.files:
                file = request.files['profile_picture']
                if file and file.filename != "":
                    # ⚠️ تم التعديل: حذف الصورة القديمة بشكل آمن
                    if g.user.profile_picture and g.user.profile_picture != 'default.png':
                        try:
                            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], g.user.profile_picture))
                        except FileNotFoundError:
                            pass
                    
                    filename = save_profile_picture(file)
                    g.user.profile_picture = filename

            db.session.commit()
            
            flash("تم تحديث ملفك الشخصي بنجاح!", "success")
            return redirect(url_for('my_profile'))

        elif "delete_account" in request.form:
            # ⚠️ تم التعديل: حذف البيانات المرتبطة بشكل صحيح
            posts_to_delete = Post.query.filter_by(user_id=g.user.id).all()
            for post in posts_to_delete:
                if post.image_url:
                    filename = os.path.basename(post.image_url)
                    image_path = os.path.join(app.config['POST_IMAGES_FOLDER'], filename)
                    if os.path.exists(image_path):
                        os.remove(image_path)
                db.session.delete(post)
            
            # ⚠️ تم التعديل: حذف صورة الملف الشخصي بشكل آمن
            if g.user.profile_picture and g.user.profile_picture != 'default.png':
                try:
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], g.user.profile_picture))
                except FileNotFoundError:
                    pass
            
            db.session.delete(g.user)
            db.session.commit()
            session.clear()
            
            flash("تم حذف الحساب بنجاح!", "success")
            return redirect(url_for("register"))
            
    user_posts = Post.query.filter_by(user_id=g.user.id).order_by(Post.timestamp.desc()).all()
    liked_post_ids = {like.post_id for like in Like.query.filter_by(user_id=g.user.id).all()}
    
    return render_template("profile.html", user_posts=user_posts, user=g.user, liked_post_ids=liked_post_ids)

@app.route("/profile/<int:user_id>")
@login_required
def user_profile(user_id):
    user = User.query.get_or_404(user_id)
    user_posts = Post.query.filter_by(user_id=user.id).order_by(Post.timestamp.desc()).all()
    liked_post_ids = {like.post_id for like in Like.query.filter_by(user_id=g.user.id).all()}
    
    return render_template("user_profile.html", user=user, user_posts=user_posts, liked_post_ids=liked_post_ids)

@app.route("/ask_tdh_ai")
@login_required
def ask_tdh_ai():
    return render_template("ask_tdh_ai.html")
# ====================
# تهيئة Gemini AI
# ====================
# ⚠️ تذكير: تأكد من إعداد مفتاح API بشكل صحيح
# سواء بوضعه مباشرة هنا أو عبر متغيرات البيئة
# genai.configure(api_key="AIzaSyBoe4Z2LespjBQ7d8d6iuroyjYgkR5PFY0")
# ====================
# النماذج (تم التحديث)
# ====================
...
# ====================
# المسارات (Routes)
# ====================
...

@app.route("/api/ask", methods=["POST"])
def ask_api():
    """
    واجهة API لاستقبال الأسئلة والإجابة عليها باستخدام نموذج Gemini.
    - تتحقق من صلاحية المستخدم.
    - تمنع الأسئلة غير المناسبة.
    - تحتوي على ردود مخصصة لبعض الأسئلة المتكررة.
    """

    # التحقق من صلاحية المستخدم
    if not getattr(g, "user", None) or g.user.status != 'approved':
        return jsonify({
            "ok": False,
            "error": "غير مصرح لك بالوصول"
        }), 403

    # الحصول على البيانات من الطلب
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()

    if not question:
        return jsonify({
            "ok": False,
            "answer": "❌ الرجاء كتابة سؤال أولاً."
        }), 400

    # الكلمات غير المسموح بها
    inappropriate_keywords = [
        'جنس', 'إباحية', 'سلوك خادش',
        'جنسي', 'عاهرة', 'دعارة', 'شواذ'
    ]

    # الردود الجاهزة (خريطة أسئلة → إجابات)
    predefined_answers = {
        "من انت؟": "أنا مساعد تيري ديس هوميس. طورني مازن القيصر ونايف عادل، طالبان بجامعة المستقبل السودانية.",
        "من أنت؟": "أنا مساعد تيري ديس هوميس. طورني مازن القيصر ونايف عادل، طالبان بجامعة المستقبل السودانية.",
        "لصالح من تعمل؟": "أنا أعمل لصالح منظمة TDH الطوعية.",
        "لصالح من تعمل": "أنا أعمل لصالح منظمة TDH الطوعية.",
        "ما هي وظيفتك؟": "أنا هنا لمساعدتك في كل ما يتعلق ببرنامج TDH.",
        "ما وظيفتك؟": "أنا هنا لمساعدتك في كل ما يتعلق ببرنامج TDH."
    }

    # تحديد الـ prompt النهائي
    if any(kw in question.lower() for kw in inappropriate_keywords):
        full_prompt = "أنا متخصص في مساعدة مستفيدي برامج المنظمة فقط."
    elif question in predefined_answers:
        full_prompt = predefined_answers[question]
    else:
        full_prompt = f"أنت مساعد متخصص في برنامج TDH. أجب على السؤال التالي بوضوح وموضوعية: {question}"

    try:
        response = model.generate_content(full_prompt)
        answer = (response.text.strip() if response and response.text 
                  else "⚠️ لا يمكنني الإجابة على هذا السؤال الآن. الرجاء المحاولة مرة أخرى.")

        return jsonify({
            "ok": True,
            "answer": answer
        })

    except Exception as e:
        app.logger.error(f"خطأ أثناء الاتصال بـ Gemini: {e}")
        return jsonify({
            "ok": False,
            "answer": "⚠️ حدث خطأ أثناء معالجة الطلب. الرجاء المحاولة لاحقًا."
        }), 500

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

    # ⚠️ تم التعديل: إضافة التحقق من هوية المستخدم
    if post.user_id != g.user.id and not g.user.is_admin:
        flash("لا يمكنك حذف منشور ليس منشورك", "danger")
        return redirect(url_for("index"))

    if post.image_url:
        filename = os.path.basename(post.image_url)
        image_path = os.path.join(app.config['POST_IMAGES_FOLDER'], filename)
        if os.path.exists(image_path):
            os.remove(image_path)
    
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
        
        admin_username = 'tdh_admin'
        admin_password = 'your_strong_admin_password_here'
        
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
        db.create_all()
        
    app.run(debug=True)
