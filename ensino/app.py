"""Ensino Ekulihiso — plataforma de ensino para Angola (ensino.ekulihiso.com).

Professores publicam conteúdos didácticos e ofertas de explicação por disciplina;
alunos inscrevem-se, comentam e acompanham as suas inscrições.
"""

import os
import re
import secrets
import sqlite3
import unicodedata
import uuid
from functools import wraps

from flask import (
    Flask, abort, current_app, flash, g, redirect, render_template, request,
    send_from_directory, session, url_for,
)
from markupsafe import Markup, escape
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Divisão político-administrativa em vigor (21 províncias)
PROVINCES = [
    "Bengo", "Benguela", "Bié", "Cabinda", "Cuando", "Cubango", "Cuanza Norte",
    "Cuanza Sul", "Cunene", "Huambo", "Huíla", "Icolo e Bengo", "Luanda",
    "Lunda Norte", "Lunda Sul", "Malanje", "Moxico", "Moxico Leste", "Namibe",
    "Uíge", "Zaire",
]

# Níveis do sistema de ensino angolano
LEVELS = [
    "Ensino Primário (1ª–6ª classe)",
    "I Ciclo do Secundário (7ª–9ª classe)",
    "II Ciclo do Secundário (10ª–13ª classe)",
    "Ensino Técnico-Profissional",
    "Preparação para Exames de Acesso",
    "Ensino Superior",
    "Formação Profissional / Adultos",
]

DISCIPLINES = [
    "Língua Portuguesa", "Matemática", "Física", "Química", "Biologia",
    "Geografia", "História", "Inglês", "Francês", "Informática",
    "Filosofia", "Educação Moral e Cívica", "Empreendedorismo",
    "Educação Física", "Desenho", "Contabilidade", "Economia",
    "Línguas Nacionais",
]

MODALITIES = ["Presencial", "Online", "Presencial e Online"]
KINDS = {"conteudo": "Conteúdo didáctico", "explicacao": "Explicação / Aulas"}
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx",
                      "png", "jpg", "jpeg", "txt"}
PER_PAGE = 12


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-mude-esta-chave"),
        DATABASE=os.environ.get("DATABASE", os.path.join(app.instance_path, "ensino.db")),
        UPLOAD_FOLDER=os.environ.get("UPLOAD_FOLDER", os.path.join(app.instance_path, "uploads")),
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,  # 10 MB por ficheiro
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
    )
    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    register_db(app)
    register_helpers(app)
    register_routes(app)

    with app.app_context():
        init_db()
    return app


# --------------------------------------------------------------------------- #
# Base de dados
# --------------------------------------------------------------------------- #

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def init_db():
    db = get_db()
    with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as f:
        db.executescript(f.read())
    for name in DISCIPLINES:
        db.execute("INSERT OR IGNORE INTO disciplines (name, slug) VALUES (?, ?)",
                   (name, slugify(name)))
    db.commit()


def register_db(app):
    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()


# --------------------------------------------------------------------------- #
# Autenticação, CSRF e filtros
# --------------------------------------------------------------------------- #

def current_user():
    if "user" not in g:
        uid = session.get("user_id")
        g.user = (get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
                  if uid else None)
    return g.user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Entre na sua conta para continuar.", "warning")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def teacher_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user()["role"] not in ("professor", "admin"):
            flash("Apenas professores podem fazer isso.", "warning")
            return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def register_helpers(app):
    @app.before_request
    def check_csrf():
        if request.method == "POST" and not app.config.get("TESTING_NO_CSRF"):
            token = request.form.get("_csrf", "")
            if not token or not secrets.compare_digest(token, session.get("_csrf", "")):
                abort(400, "Pedido inválido (token CSRF). Recarregue a página.")

    @app.context_processor
    def inject():
        return {
            "user": current_user(),
            "csrf_token": csrf_token,
            "PROVINCES": PROVINCES,
            "LEVELS": LEVELS,
            "MODALITIES": MODALITIES,
            "KINDS": KINDS,
        }

    @app.template_filter("nl2br")
    def nl2br(text):
        return Markup("<br>".join(escape(text or "").split("\n")))

    @app.template_filter("kz")
    def kz(value):
        if value is None:
            return "A combinar"
        return f"{value:,.0f} Kz".replace(",", ".")

    @app.template_filter("date")
    def date(value):
        return (value or "")[:10]

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404,
                               message="Página não encontrada."), 404

    @app.errorhandler(413)
    def too_large(_e):
        return render_template("error.html", code=413,
                               message="Ficheiro demasiado grande (máximo 10 MB)."), 413

    @app.errorhandler(400)
    def bad_request(e):
        return render_template("error.html", code=400, message=e.description), 400


# --------------------------------------------------------------------------- #
# Consultas
# --------------------------------------------------------------------------- #

POST_SELECT = """
    SELECT p.*, d.name AS discipline, d.slug AS discipline_slug,
           u.name AS teacher, u.province AS teacher_province,
           (SELECT COUNT(*) FROM enrollments e WHERE e.post_id = p.id) AS enrolled
    FROM posts p
    JOIN disciplines d ON d.id = p.discipline_id
    JOIN users u ON u.id = p.teacher_id
"""


def get_post(post_id):
    post = get_db().execute(POST_SELECT + " WHERE p.id = ?", (post_id,)).fetchone()
    if post is None:
        abort(404)
    return post


def get_own_post(post_id):
    post = get_post(post_id)
    user = current_user()
    if post["teacher_id"] != user["id"] and user["role"] != "admin":
        abort(403)
    return post


def save_attachment(file):
    if not file or not file.filename:
        return None, None
    name = secure_filename(file.filename)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Tipo de ficheiro não permitido.")
    stored = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], stored))
    return stored, name


def read_post_form():
    """Valida o formulário de publicação. Devolve (dados, erros)."""
    f = request.form
    data = {
        "kind": f.get("kind", ""),
        "discipline_id": f.get("discipline_id", type=int),
        "title": f.get("title", "").strip(),
        "summary": f.get("summary", "").strip(),
        "body": f.get("body", "").strip(),
        "level": f.get("level", ""),
        "modality": f.get("modality") or None,
        "province": f.get("province") or None,
        "price": f.get("price", type=int),
    }
    errors = []
    if data["kind"] not in KINDS:
        errors.append("Escolha o tipo de publicação.")
    if not data["discipline_id"] or not get_db().execute(
            "SELECT 1 FROM disciplines WHERE id = ?", (data["discipline_id"],)).fetchone():
        errors.append("Escolha uma disciplina.")
    if not 5 <= len(data["title"]) <= 150:
        errors.append("O título deve ter entre 5 e 150 caracteres.")
    if not 10 <= len(data["summary"]) <= 300:
        errors.append("O resumo deve ter entre 10 e 300 caracteres.")
    if len(data["body"]) < 20:
        errors.append("O conteúdo deve ter pelo menos 20 caracteres.")
    if data["level"] not in LEVELS:
        errors.append("Escolha o nível de ensino.")
    if data["kind"] == "explicacao":
        if data["modality"] not in MODALITIES:
            errors.append("Escolha a modalidade das aulas.")
        if data["province"] and data["province"] not in PROVINCES:
            errors.append("Província inválida.")
        if data["price"] is not None and data["price"] < 0:
            errors.append("O preço não pode ser negativo.")
    else:
        data.update(modality=None, province=None, price=None)
    return data, errors


# --------------------------------------------------------------------------- #
# Rotas
# --------------------------------------------------------------------------- #

def register_routes(app):

    @app.route("/")
    def index():
        db = get_db()
        latest = db.execute(POST_SELECT + " ORDER BY p.created_at DESC, p.id DESC LIMIT 6").fetchall()
        disciplines = db.execute("""
            SELECT d.*, COUNT(p.id) AS total FROM disciplines d
            LEFT JOIN posts p ON p.discipline_id = d.id
            GROUP BY d.id ORDER BY total DESC, d.name LIMIT 12""").fetchall()
        stats = {
            "alunos": db.execute("SELECT COUNT(*) FROM users WHERE role='aluno'").fetchone()[0],
            "professores": db.execute("SELECT COUNT(*) FROM users WHERE role='professor'").fetchone()[0],
            "conteudos": db.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
        }
        return render_template("index.html", latest=latest, disciplines=disciplines, stats=stats)

    @app.route("/sobre")
    def about():
        return render_template("about.html")

    # ---- Contas ----------------------------------------------------------- #

    @app.route("/registar", methods=["GET", "POST"])
    def register():
        if current_user():
            return redirect(url_for("dashboard"))
        form = request.form
        if request.method == "POST":
            name = form.get("name", "").strip()
            email = form.get("email", "").strip().lower()
            password = form.get("password", "")
            role = form.get("role", "")
            province = form.get("province", "")
            level = form.get("level") or None
            errors = []
            if len(name) < 3:
                errors.append("Indique o seu nome completo.")
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                errors.append("Email inválido.")
            if len(password) < 8:
                errors.append("A palavra-passe deve ter pelo menos 8 caracteres.")
            if password != form.get("confirmation", ""):
                errors.append("As palavras-passe não coincidem.")
            if role not in ("aluno", "professor"):
                errors.append("Escolha se é aluno ou professor.")
            if province not in PROVINCES:
                errors.append("Escolha a sua província.")
            if level and level not in LEVELS:
                errors.append("Nível de ensino inválido.")
            if not errors:
                db = get_db()
                try:
                    cur = db.execute(
                        "INSERT INTO users (name, email, password_hash, role, province, level, phone) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (name, email, generate_password_hash(password), role, province, level,
                         form.get("phone", "").strip()[:30]))
                    db.commit()
                except sqlite3.IntegrityError:
                    errors.append("Já existe uma conta com este email.")
                else:
                    session.clear()
                    session["user_id"] = cur.lastrowid
                    flash(f"Bem-vindo(a), {name}! A sua conta foi criada.", "success")
                    return redirect(url_for("dashboard"))
            for e in errors:
                flash(e, "danger")
        return render_template("register.html", form=form,
                               role=request.args.get("tipo", form.get("role", "aluno")))

    @app.route("/entrar", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            row = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if row is None or not check_password_hash(row["password_hash"],
                                                      request.form.get("password", "")):
                flash("Email ou palavra-passe incorrectos.", "danger")
                return render_template("login.html", email=email), 401
            session.clear()
            session["user_id"] = row["id"]
            flash(f"Olá, {row['name']}!", "success")
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//")
                            else url_for("dashboard"))
        return render_template("login.html", email="")

    @app.route("/sair", methods=["POST"])
    def logout():
        session.clear()
        flash("Sessão terminada.", "info")
        return redirect(url_for("index"))

    @app.route("/perfil", methods=["GET", "POST"])
    @login_required
    def profile():
        user = current_user()
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            province = request.form.get("province", "")
            level = request.form.get("level") or None
            if len(name) < 3 or province not in PROVINCES or (level and level not in LEVELS):
                flash("Verifique os dados do perfil.", "danger")
            else:
                db = get_db()
                db.execute("UPDATE users SET name=?, province=?, level=?, bio=?, phone=? WHERE id=?",
                           (name, province, level, request.form.get("bio", "").strip()[:1000],
                            request.form.get("phone", "").strip()[:30], user["id"]))
                new_pw = request.form.get("new_password", "")
                if new_pw:
                    if len(new_pw) < 8:
                        flash("A nova palavra-passe deve ter pelo menos 8 caracteres.", "danger")
                        return redirect(url_for("profile"))
                    db.execute("UPDATE users SET password_hash=? WHERE id=?",
                               (generate_password_hash(new_pw), user["id"]))
                db.commit()
                flash("Perfil actualizado.", "success")
                return redirect(url_for("profile"))
        return render_template("profile.html")

    @app.route("/painel")
    @login_required
    def dashboard():
        db = get_db()
        user = current_user()
        if user["role"] in ("professor", "admin"):
            posts = db.execute(POST_SELECT + " WHERE p.teacher_id = ? ORDER BY p.created_at DESC",
                               (user["id"],)).fetchall()
            students = db.execute("""
                SELECT e.created_at, e.message, s.name, s.email, s.phone, s.province, s.level,
                       p.id AS post_id, p.title
                FROM enrollments e
                JOIN posts p ON p.id = e.post_id
                JOIN users s ON s.id = e.student_id
                WHERE p.teacher_id = ? ORDER BY e.created_at DESC""", (user["id"],)).fetchall()
            return render_template("dashboard_teacher.html", posts=posts, students=students)
        enrollments = db.execute(POST_SELECT + """
            JOIN enrollments en ON en.post_id = p.id
            WHERE en.student_id = ? ORDER BY en.created_at DESC""", (user["id"],)).fetchall()
        suggested = db.execute(POST_SELECT + " WHERE p.level = ? ORDER BY p.created_at DESC LIMIT 6",
                               (user["level"] or "",)).fetchall()
        return render_template("dashboard_student.html", enrollments=enrollments,
                               suggested=suggested)

    # ---- Conteúdos -------------------------------------------------------- #

    @app.route("/conteudos")
    def posts():
        db = get_db()
        args = request.args
        where, params = [], []
        if args.get("q"):
            where.append("(p.title LIKE ? OR p.summary LIKE ? OR p.body LIKE ?)")
            params += [f"%{args['q']}%"] * 3
        if args.get("disciplina"):
            where.append("d.slug = ?")
            params.append(args["disciplina"])
        if args.get("nivel") in LEVELS:
            where.append("p.level = ?")
            params.append(args["nivel"])
        if args.get("tipo") in KINDS:
            where.append("p.kind = ?")
            params.append(args["tipo"])
        if args.get("provincia") in PROVINCES:
            where.append("(p.province = ? OR p.modality != 'Presencial')")
            params.append(args["provincia"])
        sql_where = (" WHERE " + " AND ".join(where)) if where else ""
        page = max(args.get("pagina", 1, type=int), 1)
        total = db.execute("SELECT COUNT(*) FROM posts p JOIN disciplines d ON d.id = p.discipline_id"
                           + sql_where, params).fetchone()[0]
        rows = db.execute(POST_SELECT + sql_where +
                          " ORDER BY p.created_at DESC, p.id DESC LIMIT ? OFFSET ?",
                          params + [PER_PAGE, (page - 1) * PER_PAGE]).fetchall()
        disciplines = db.execute("SELECT * FROM disciplines ORDER BY name").fetchall()
        pages = max((total + PER_PAGE - 1) // PER_PAGE, 1)
        return render_template("posts.html", posts=rows, disciplines=disciplines,
                               total=total, page=page, pages=pages)

    @app.route("/disciplinas")
    def disciplines():
        rows = get_db().execute("""
            SELECT d.*, COUNT(p.id) AS total,
                   SUM(p.kind = 'explicacao') AS offers
            FROM disciplines d LEFT JOIN posts p ON p.discipline_id = d.id
            GROUP BY d.id ORDER BY d.name""").fetchall()
        return render_template("disciplines.html", disciplines=rows)

    @app.route("/conteudos/<int:post_id>")
    def post_detail(post_id):
        post = get_post(post_id)
        db = get_db()
        comments = db.execute("""
            SELECT c.*, u.name, u.role FROM comments c JOIN users u ON u.id = c.user_id
            WHERE c.post_id = ? ORDER BY c.created_at""", (post_id,)).fetchall()
        user = current_user()
        enrolled = bool(user and db.execute(
            "SELECT 1 FROM enrollments WHERE student_id=? AND post_id=?",
            (user["id"], post_id)).fetchone())
        return render_template("post.html", post=post, comments=comments, enrolled=enrolled)

    @app.route("/publicar", methods=["GET", "POST"])
    @teacher_required
    def new_post():
        disciplines = get_db().execute("SELECT * FROM disciplines ORDER BY name").fetchall()
        if request.method == "POST":
            data, errors = read_post_form()
            if not errors:
                try:
                    stored, original = save_attachment(request.files.get("attachment"))
                except ValueError as e:
                    errors.append(str(e))
            if errors:
                for e in errors:
                    flash(e, "danger")
                return render_template("post_form.html", disciplines=disciplines,
                                       post=request.form, editing=False), 422
            db = get_db()
            cur = db.execute("""
                INSERT INTO posts (teacher_id, discipline_id, kind, title, summary, body, level,
                                   modality, province, price, attachment, attachment_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (current_user()["id"], data["discipline_id"], data["kind"], data["title"],
                 data["summary"], data["body"], data["level"], data["modality"],
                 data["province"], data["price"], stored, original))
            db.commit()
            flash("Publicação criada com sucesso!", "success")
            return redirect(url_for("post_detail", post_id=cur.lastrowid))
        kind = request.args.get("tipo", "conteudo")
        return render_template("post_form.html", disciplines=disciplines,
                               post={"kind": kind}, editing=False)

    @app.route("/conteudos/<int:post_id>/editar", methods=["GET", "POST"])
    @teacher_required
    def edit_post(post_id):
        post = get_own_post(post_id)
        disciplines = get_db().execute("SELECT * FROM disciplines ORDER BY name").fetchall()
        if request.method == "POST":
            data, errors = read_post_form()
            stored, original = post["attachment"], post["attachment_name"]
            if not errors and request.files.get("attachment") and request.files["attachment"].filename:
                try:
                    stored, original = save_attachment(request.files["attachment"])
                except ValueError as e:
                    errors.append(str(e))
                else:
                    remove_upload(post["attachment"])
            if errors:
                for e in errors:
                    flash(e, "danger")
                return render_template("post_form.html", disciplines=disciplines,
                                       post=request.form, editing=True, post_id=post_id), 422
            db = get_db()
            db.execute("""
                UPDATE posts SET discipline_id=?, kind=?, title=?, summary=?, body=?, level=?,
                       modality=?, province=?, price=?, attachment=?, attachment_name=?,
                       updated_at=CURRENT_TIMESTAMP
                WHERE id=?""",
                (data["discipline_id"], data["kind"], data["title"], data["summary"],
                 data["body"], data["level"], data["modality"], data["province"],
                 data["price"], stored, original, post_id))
            db.commit()
            flash("Publicação actualizada.", "success")
            return redirect(url_for("post_detail", post_id=post_id))
        return render_template("post_form.html", disciplines=disciplines, post=post,
                               editing=True, post_id=post_id)

    @app.route("/conteudos/<int:post_id>/apagar", methods=["POST"])
    @teacher_required
    def delete_post(post_id):
        post = get_own_post(post_id)
        db = get_db()
        db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        db.commit()
        remove_upload(post["attachment"])
        flash("Publicação apagada.", "info")
        return redirect(url_for("dashboard"))

    @app.route("/conteudos/<int:post_id>/inscrever", methods=["POST"])
    @login_required
    def enroll(post_id):
        post = get_post(post_id)
        user = current_user()
        if user["role"] != "aluno":
            flash("Apenas alunos se podem inscrever.", "warning")
        elif post["kind"] != "explicacao":
            flash("Só é possível inscrever-se em ofertas de explicação.", "warning")
        else:
            db = get_db()
            db.execute("INSERT OR IGNORE INTO enrollments (student_id, post_id, message) VALUES (?, ?, ?)",
                       (user["id"], post_id, request.form.get("message", "").strip()[:500]))
            db.commit()
            flash("Inscrição feita! O professor vai entrar em contacto consigo.", "success")
        return redirect(url_for("post_detail", post_id=post_id))

    @app.route("/conteudos/<int:post_id>/cancelar", methods=["POST"])
    @login_required
    def unenroll(post_id):
        db = get_db()
        db.execute("DELETE FROM enrollments WHERE student_id=? AND post_id=?",
                   (current_user()["id"], post_id))
        db.commit()
        flash("Inscrição cancelada.", "info")
        return redirect(url_for("post_detail", post_id=post_id))

    @app.route("/conteudos/<int:post_id>/comentar", methods=["POST"])
    @login_required
    def comment(post_id):
        get_post(post_id)
        body = request.form.get("body", "").strip()
        if not 2 <= len(body) <= 2000:
            flash("O comentário deve ter entre 2 e 2000 caracteres.", "danger")
        else:
            db = get_db()
            db.execute("INSERT INTO comments (post_id, user_id, body) VALUES (?, ?, ?)",
                       (post_id, current_user()["id"], body))
            db.commit()
        return redirect(url_for("post_detail", post_id=post_id) + "#comentarios")

    @app.route("/ficheiros/<int:post_id>")
    def download(post_id):
        post = get_post(post_id)
        if not post["attachment"]:
            abort(404)
        return send_from_directory(app.config["UPLOAD_FOLDER"], post["attachment"],
                                   as_attachment=True, download_name=post["attachment_name"])

    # ---- Professores ------------------------------------------------------ #

    @app.route("/professores")
    def teachers():
        rows = get_db().execute("""
            SELECT u.id, u.name, u.province, u.bio, COUNT(p.id) AS total,
                   GROUP_CONCAT(DISTINCT d.name) AS subjects
            FROM users u
            LEFT JOIN posts p ON p.teacher_id = u.id
            LEFT JOIN disciplines d ON d.id = p.discipline_id
            WHERE u.role = 'professor'
            GROUP BY u.id ORDER BY total DESC, u.name""").fetchall()
        return render_template("teachers.html", teachers=rows)

    @app.route("/professores/<int:user_id>")
    def teacher(user_id):
        db = get_db()
        t = db.execute("SELECT * FROM users WHERE id = ? AND role IN ('professor','admin')",
                       (user_id,)).fetchone()
        if t is None:
            abort(404)
        posts = db.execute(POST_SELECT + " WHERE p.teacher_id = ? ORDER BY p.created_at DESC",
                           (user_id,)).fetchall()
        return render_template("teacher.html", teacher=t, posts=posts)

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403, message="Sem permissão."), 403


def remove_upload(stored):
    if stored:
        try:
            os.remove(os.path.join(current_app.config["UPLOAD_FOLDER"], stored))
        except OSError:
            pass


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
