from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, g, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import os
import google.generativeai as genai

# ====================
# تهيئة التطبيق
# ====================
app = Flask(__name__)
app.secret_key = "secret_key_for_session"
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
# تأكد من أن مفتاح API صحيح، ولا تقم بنشره في مكان عام
API_KEY = "AIzaSyClaPw9XKcffyk3vGzSrGRCtlS_HoVlNVk"
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel(model_name="models/gemini-1.5-flash")

# ====================
# النماذج
# ====================
class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    training_course = db.Column(db.String(120), nullable=True)
    profile_picture = db.Column(db.String(255), nullable=True, default='default.png')
    # حقل جديد لوصف المستخدم
    bio = db.Column(db.Text, nullable=True, default="لا يوجد وصف شخصي حتى الآن.")
    
    # خاصية لإنشاء مسار URL لصورة الملف الشخصي، لتجنب الأخطاء في القوالب
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

# ====================
# الدوال المساعدة
# ====================
# دالة لجلب المستخدم الحالي من الجلسة
def get_current_user():
    if 'user_id' in session:
        return User.query.get(session['user_id'])
    return None

def save_profile_picture(file):
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(file_path)
    return filename

# ====================
# جعل المستخدم الحالي متاحًا لجميع القوالب
# ====================
@app.before_request
def before_request():
    g.user = get_current_user()

@app.context_processor
def inject_user():
    return dict(current_user=g.user)

# ====================
# المسارات (Routes)
# ====================
@app.route("/")
def index():
    if not g.user:
        return redirect(url_for("login"))
    
    posts = Post.query.order_by(Post.timestamp.desc()).all()
    # لتحسين الأداء، نجمع المنشورات التي أعجب بها المستخدم الحالي
    liked_post_ids = set()
    if g.user:
        liked_post_ids = {like.post_id for like in Like.query.filter_by(user_id=g.user.id).all()}

    return render_template("index.html", posts=posts, liked_post_ids=liked_post_ids)

@app.route("/intro")
def intro():
    if not g.user:
        return redirect(url_for("login"))
    return render_template("intro.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        confirm = request.form.get("confirm")
        if password != confirm:
            flash("كلمتا المرور غير متطابقتين", "warning")
            return redirect(url_for("register"))
        if User.query.filter_by(username=username).first():
            flash("اسم المستخدم موجود بالفعل", "warning")
            return redirect(url_for("register"))
        user = User(username=username, password=password)
        db.session.add(user)
        db.session.commit()
        session['user_id'] = user.id
        flash("تم إنشاء الحساب بنجاح! مرحباً بك.", "success")
        return redirect(url_for("intro"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index"))
        
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            session['user_id'] = user.id
            flash("تم تسجيل الدخول بنجاح", "success")
            return redirect(url_for("intro"))
        flash("اسم المستخدم أو كلمة المرور غير صحيحة.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("تم تسجيل الخروج", "success")
    return redirect(url_for("login"))

@app.route("/post_question", methods=["POST"])
def post_question():
    if not g.user:
        return redirect(url_for("login"))
    content = request.form.get("content").strip()
    if content:
        post = Post(user_id=g.user.id, content=content)
        db.session.add(post)
        db.session.commit()
        flash("تم نشر سؤالك بنجاح!", "success")
    return redirect(url_for("index"))

@app.route("/like/<int:post_id>", methods=["POST"])
def like(post_id):
    if not g.user:
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
def comment_post(post_id):
    if not g.user:
        return redirect(url_for("login"))
    content = request.form.get("content").strip()
    if content:
        comment = Comment(post_id=post_id, user_id=g.user.id, content=content)
        db.session.add(comment)
        db.session.commit()
        flash("تم إضافة تعليقك!", "success")
    return redirect(url_for("index"))

@app.route("/profile", methods=["GET", "POST"])
def my_profile():
    if not g.user:
        return redirect(url_for("login"))
    
    if request.method == "POST":
        if "update_course" in request.form:
            g.user.training_course = request.form.get("training_course", "").strip()
            db.session.commit()
            flash("تم تحديث اسم الدورة التدريبية", "success")
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
def user_profile(user_id):
    user = User.query.get_or_404(user_id)
    user_posts = Post.query.filter_by(user_id=user.id).order_by(Post.timestamp.desc()).all()
    # يمكننا تمرير المستخدم الحالي أيضًا للاستخدام في الهيدر
    return render_template("user_profile.html", user=user, user_posts=user_posts)

@app.route("/ask_tdh_ai")
def ask_tdh_ai():
    if not g.user:
        return redirect(url_for("login"))
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
        print(f"خطأ أثناء الاتصال بـ Gemini: {e}")
        return jsonify({"answer": "⚠️ حدث خطأ أثناء معالجة الطلب. الرجاء المحاولة لاحقًا."})

@app.route("/centers")
def centers():
    if not g.user:
        return redirect(url_for("login"))
    centers_list = [
        {"name": "مركز TDH القاهرة", "location": "القاهرة - شارع التحرير", "hours": "9 صباحاً - 5 مساءً"},
        {"name": "مركز TDH الإسكندرية", "location": "الإسكندرية - شارع البحر", "hours": "10 صباحاً - 6 مساءً"},
    ]
    return render_template("centers.html", centers=centers_list)

@app.route("/delete_post/<int:post_id>", methods=["POST"])
def delete_post(post_id):
    if not g.user:
        return jsonify({"error": "غير مصرح لك"}), 403
    
    post = Post.query.get_or_404(post_id)
    if post.user_id != g.user.id:
        flash("لا يمكنك حذف منشور ليس منشورك", "danger")
        return redirect(url_for("index"))
    
    # حذف التعليقات والإعجابات المرتبطة بالمنشور أولاً
    Comment.query.filter_by(post_id=post_id).delete()
    Like.query.filter_by(post_id=post_id).delete()
    
    db.session.delete(post)
    db.session.commit()
    flash("تم حذف المنشور", "success")
    return redirect(url_for("index"))

# ====================
# تشغيل التطبيق
# ====================
if __name__ == "__main__":
    app.run(debug=True)

# إضافة أمر مخصص لإنشاء قاعدة البيانات من سطر الأوامر
@app.cli.command("create-db")
def create_db():
    with app.app_context():
        db.create_all()
        print("تم إنشاء جداول قاعدة البيانات بنجاح.")
