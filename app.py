from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
import google.generativeai as genai

app = Flask(__name__)
app.secret_key = "secret_key_for_session"  # عدله لما تريد
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///tdh.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# Google Gemini API Key
API_KEY = "AIzaSyClaPw9XKcffyk3vGzSrGRCtlS_HoVlNVk"
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel(model_name="models/gemini-1.5-flash")

# النماذج مع تحديد أسماء الجداول
class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    training_course = db.Column(db.String(120), nullable=True)

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

# Helpers
def current_user():
    if 'user_id' in session:
        return User.query.get(session['user_id'])
    return None

# Routes

@app.route("/")
def index():
    if not current_user():
        return redirect(url_for("login"))
    posts = Post.query.order_by(Post.timestamp.desc()).all()
    return render_template("index.html", posts=posts)

@app.route("/intro")
def intro():
    if not current_user():
        return redirect(url_for("login"))
    return render_template("intro.html", session=session)

@app.route("/register.html", methods=["GET", "POST"])
def register():
    # منع المستخدمين المسجلين من رؤية صفحة التسجيل
    if current_user():
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username").strip()
        email = request.form.get("email").strip()
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
        session['username'] = user.username
        return redirect(url_for("intro"))
    return render_template("register.html")

@app.route("/login.html", methods=["GET", "POST"])
def login():
    # منع المستخدمين المسجلين من رؤية صفحة تسجيل الدخول
    if current_user():
        return redirect(url_for("index"))
        
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            session['user_id'] = user.id
            session['username'] = user.username
            return redirect(url_for("intro"))
        flash("اسم المستخدم أو كلمة المرور غير صحيحة.", "danger")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/post_question", methods=["POST"])
def post_question():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    content = request.form.get("content").strip()
    if content:
        post = Post(user_id=user.id, content=content)
        db.session.add(post)
        db.session.commit()
    return redirect(url_for("index"))

@app.route("/like/<int:post_id>", methods=["POST"])
def like(post_id):
    user = current_user()
    if not user:
        return jsonify({"error": "غير مسموح"}), 403
    post = Post.query.get_or_404(post_id)
    like = Like.query.filter_by(user_id=user.id, post_id=post_id).first()

    if like:
        # إزالة الإعجاب
        db.session.delete(like)
        post.likes = max(post.likes - 1, 0)
        liked = False
    else:
        # إضافة إعجاب جديد
        new_like = Like(user_id=user.id, post_id=post_id)
        db.session.add(new_like)
        post.likes += 1
        liked = True

    db.session.commit()
    return jsonify({"likes": post.likes, "liked": liked})

@app.route("/comment/<int:post_id>", methods=["POST"])
def comment_post(post_id):
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    content = request.form.get("content").strip()
    if content:
        comment = Comment(post_id=post_id, user_id=user.id, content=content)
        db.session.add(comment)
        db.session.commit()
    return redirect(url_for("index"))

@app.route("/profile", methods=["GET", "POST"])
def profile():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    if request.method == "POST":
        if "update_course" in request.form:
            new_course = request.form.get("training_course", "").strip()
            user.training_course = new_course
            db.session.commit()
            flash("تم تحديث اسم الدورة التدريبية", "success")
        elif "delete_account" in request.form:
            db.session.delete(user)
            db.session.commit()
            session.clear()
            flash("تم حذف الحساب", "success")
            return redirect(url_for("register"))
    return render_template("profile.html", user=user)

@app.route("/ask_tdh_ai")
def ask_tdh_ai():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    return render_template("ask_tdh_ai.html")

@app.route("/api/ask", methods=["POST"])
def ask_api():
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
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    centers = [
        {"name": "مركز TDH القاهرة", "location": "القاهرة - شارع التحرير", "hours": "9 صباحاً - 5 مساءً"},
        {"name": "مركز TDH الإسكندرية", "location": "الإسكندرية - شارع البحر", "hours": "10 صباحاً - 6 مساءً"},
    ]
    return render_template("centers.html", centers=centers)

@app.route("/delete_post/<int:post_id>", methods=["POST"])
def delete_post(post_id):
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    post = Post.query.get_or_404(post_id)
    if post.user_id != user.id:
        flash("لا يمكنك حذف منشور غير منشورك", "danger")
        return redirect(url_for("index"))
    db.session.delete(post)
    db.session.commit()
    flash("تم حذف المنشور", "success")
    return redirect(url_for("index"))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        inspector = db.inspect(db.engine)
        print("تم إنشاء الجداول التالية في قاعدة البيانات:")
        print(inspector.get_table_names())

    app.run(debug=True)