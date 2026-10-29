"""Ensino Ekulihiso — plataforma de ensino para Angola (ensino.ekulihiso.com).

Professores publicam conteúdos didácticos e anunciam aulas com preço por hora;
alunos reservam, pagam por Referência Multicaixa ou transferência e comentam.
"""

import os
import re
import secrets
import sqlite3
import unicodedata
import uuid
from datetime import date, timedelta
from functools import wraps

import click

from flask import (
    Flask, abort, current_app, flash, g, redirect, render_template, request,
    send_from_directory, session, url_for,
)

import payments
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
PROOF_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}
PER_PAGE = 12
HOURS_CHOICES = [1, 2, 3, 4]

# Estado da reserva -> (texto para o utilizador, cor Bootstrap)
BOOKING_STATUS = {
    "pendente": ("Aguarda resposta do professor", "warning"),
    "aceite": ("Aguarda pagamento", "info"),
    "paga": ("Confirmada", "success"),
    "concluida": ("Concluída", "secondary"),
    "recusada": ("Recusada", "danger"),
    "cancelada": ("Cancelada", "dark"),
}


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
        # Pagamentos
        COMMISSION_PERCENT=int(os.environ.get("COMMISSION_PERCENT", "10")),
        PROXYPAY_API_KEY=os.environ.get("PROXYPAY_API_KEY", ""),
        PROXYPAY_ENTITY=os.environ.get("PROXYPAY_ENTITY", ""),
        PROXYPAY_ENV=os.environ.get("PROXYPAY_ENV", "sandbox"),
        # Sem SECRET_KEY definida (desenvolvimento) os pagamentos são simulados
        PAYMENTS_SANDBOX=os.environ.get(
            "PAYMENTS_SANDBOX", "0" if "SECRET_KEY" in os.environ else "1") == "1",
        BANK_NAME=os.environ.get("BANK_NAME", ""),
        BANK_HOLDER=os.environ.get("BANK_HOLDER", ""),
        BANK_IBAN=os.environ.get("BANK_IBAN", ""),
    )
    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    register_db(app)
    register_helpers(app)
    register_routes(app)
    register_booking_routes(app)
    register_admin(app)

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
    # Colunas acrescentadas depois da primeira versão
    for table, column, decl in [("users", "iban", "TEXT NOT NULL DEFAULT ''"),
                                ("posts", "first_lesson_free", "INTEGER NOT NULL DEFAULT 0")]:
        if column not in {r[1] for r in db.execute(f"PRAGMA table_info({table})")}:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
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


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user()["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def register_helpers(app):
    @app.before_request
    def check_csrf():
        if (request.method == "POST" and not app.config.get("TESTING_NO_CSRF")
                and request.endpoint != "proxypay_webhook"):
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
            "BOOKING_STATUS": BOOKING_STATUS,
            "HOURS_CHOICES": HOURS_CHOICES,
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
           (SELECT COUNT(DISTINCT b.student_id) FROM bookings b
             WHERE b.post_id = p.id AND b.status IN ('paga', 'concluida')) AS enrolled
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


def save_attachment(file, allowed=ALLOWED_EXTENSIONS):
    if not file or not file.filename:
        return None, None
    name = secure_filename(file.filename)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in allowed:
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
        "first_lesson_free": 1 if f.get("first_lesson_free") else 0,
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
        if data["price"] is None or data["price"] < 500:
            errors.append("Indique o preço por hora (mínimo 500 Kz).")
    else:
        data.update(modality=None, province=None, price=None, first_lesson_free=0)
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
            iban = re.sub(r"\s+", "", request.form.get("iban", "")).upper()
            if len(name) < 3 or province not in PROVINCES or (level and level not in LEVELS):
                flash("Verifique os dados do perfil.", "danger")
            elif iban and not re.fullmatch(r"AO06\d{21}", iban):
                flash("IBAN inválido. Um IBAN angolano tem o formato AO06 seguido de 21 dígitos.",
                      "danger")
            else:
                db = get_db()
                db.execute("UPDATE users SET name=?, province=?, level=?, bio=?, phone=?, iban=? "
                           "WHERE id=?",
                           (name, province, level, request.form.get("bio", "").strip()[:1000],
                            request.form.get("phone", "").strip()[:30], iban, user["id"]))
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
            bookings = db.execute(BOOKING_SELECT + """
                WHERE b.teacher_id = ?
                ORDER BY b.status = 'pendente' DESC, b.lesson_date DESC, b.id DESC""",
                (user["id"],)).fetchall()
            earnings = db.execute("""
                SELECT COALESCE(SUM(CASE WHEN payout_status = 'pago' THEN teacher_amount END), 0),
                       COALESCE(SUM(CASE WHEN payout_status = 'por_pagar' THEN teacher_amount END), 0)
                FROM bookings WHERE teacher_id = ? AND status IN ('paga', 'concluida')""",
                (user["id"],)).fetchone()
            return render_template("dashboard_teacher.html", posts=posts, bookings=bookings,
                                   paid_out=earnings[0], to_receive=earnings[1])
        bookings = db.execute(BOOKING_SELECT + " WHERE b.student_id = ? ORDER BY b.id DESC",
                              (user["id"],)).fetchall()
        suggested = db.execute(POST_SELECT + " WHERE p.level = ? ORDER BY p.created_at DESC LIMIT 6",
                               (user["level"] or "",)).fetchall()
        return render_template("dashboard_student.html", bookings=bookings,
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
        free_trial = bool(post["first_lesson_free"] and (
            not user or first_booking_with(user["id"], post["teacher_id"])))
        return render_template("post.html", post=post, comments=comments,
                               free_trial=free_trial, today=date.today().isoformat())

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
                                   modality, province, price, first_lesson_free,
                                   attachment, attachment_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (current_user()["id"], data["discipline_id"], data["kind"], data["title"],
                 data["summary"], data["body"], data["level"], data["modality"],
                 data["province"], data["price"], data["first_lesson_free"], stored, original))
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
                       modality=?, province=?, price=?, first_lesson_free=?, attachment=?,
                       attachment_name=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?""",
                (data["discipline_id"], data["kind"], data["title"], data["summary"],
                 data["body"], data["level"], data["modality"], data["province"],
                 data["price"], data["first_lesson_free"], stored, original, post_id))
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


# --------------------------------------------------------------------------- #
# Reservas e pagamentos
# --------------------------------------------------------------------------- #

BOOKING_SELECT = """
    SELECT b.*,
           s.name AS student_name, s.email AS student_email, s.phone AS student_phone,
           s.province AS student_province, s.level AS student_level,
           t.name AS teacher_name, t.email AS teacher_email, t.phone AS teacher_phone,
           t.iban AS teacher_iban
    FROM bookings b
    JOIN users s ON s.id = b.student_id
    JOIN users t ON t.id = b.teacher_id
"""


def first_booking_with(student_id, teacher_id):
    """A 1ª aula grátis só vale para a primeira reserva com cada professor."""
    return get_db().execute("""
        SELECT 1 FROM bookings WHERE student_id = ? AND teacher_id = ?
        AND status NOT IN ('recusada', 'cancelada')""", (student_id, teacher_id)).fetchone() is None


def get_booking(booking_id):
    """Reserva visível apenas para o aluno, o professor e os administradores."""
    booking = get_db().execute(BOOKING_SELECT + " WHERE b.id = ?", (booking_id,)).fetchone()
    if booking is None:
        abort(404)
    user = current_user()
    if user["id"] not in (booking["student_id"], booking["teacher_id"]) and user["role"] != "admin":
        abort(403)
    return booking


def set_status(booking_id, status, from_statuses, note=None, **fields):
    """Muda o estado só se a reserva ainda estiver num dos estados esperados."""
    cols = ", ".join(f"{k} = ?" for k in fields)
    sql = (f"UPDATE bookings SET status = ?, updated_at = CURRENT_TIMESTAMP"
           f"{', status_note = ?' if note is not None else ''}{', ' + cols if cols else ''} "
           f"WHERE id = ? AND status IN ({', '.join('?' * len(from_statuses))})")
    params = [status] + ([note] if note is not None else []) + list(fields.values())
    db = get_db()
    changed = db.execute(sql, params + [booking_id] + list(from_statuses)).rowcount
    db.commit()
    return changed == 1


def mark_paid(booking_id, method):
    return set_status(booking_id, "paga", ("aceite",), payment_method=method,
                      paid_at=sql_now())


def sql_now():
    return get_db().execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]


def register_booking_routes(app):

    @app.route("/conteudos/<int:post_id>/reservar", methods=["POST"])
    @login_required
    def book(post_id):
        post = get_post(post_id)
        user = current_user()
        back = redirect(url_for("post_detail", post_id=post_id) + "#reservar")
        if user["role"] != "aluno":
            flash("Apenas alunos podem reservar aulas.", "warning")
            return back
        if post["kind"] != "explicacao" or not post["price"]:
            flash("Este anúncio não aceita reservas.", "warning")
            return back
        f = request.form
        errors = []
        try:
            lesson_date = date.fromisoformat(f.get("lesson_date", ""))
            if not date.today() <= lesson_date <= date.today() + timedelta(days=180):
                raise ValueError
        except ValueError:
            errors.append("Escolha uma data entre hoje e os próximos 6 meses.")
            lesson_date = None
        lesson_time = f.get("lesson_time", "")
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", lesson_time):
            errors.append("Indique a hora da aula.")
        hours = f.get("hours", type=int)
        if hours not in HOURS_CHOICES:
            errors.append("Escolha a duração da aula.")
        modality = post["modality"]
        if modality == "Presencial e Online":
            modality = f.get("modality", "")
            if modality not in ("Presencial", "Online"):
                errors.append("Escolha se a aula é presencial ou online.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return back
        free_hours = 1 if post["first_lesson_free"] and first_booking_with(
            user["id"], post["teacher_id"]) else 0
        amount = post["price"] * (hours - free_hours)
        commission = round(amount * app.config["COMMISSION_PERCENT"] / 100)
        db = get_db()
        cur = db.execute("""
            INSERT INTO bookings (post_id, post_title, student_id, teacher_id, lesson_date,
                                  lesson_time, hours, modality, message, price_per_hour,
                                  free_hours, amount, commission, teacher_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (post_id, post["title"], user["id"], post["teacher_id"], lesson_date.isoformat(),
             lesson_time, hours, modality, f.get("message", "").strip()[:1000], post["price"],
             free_hours, amount, commission, amount - commission))
        db.commit()
        flash("Pedido de reserva enviado! Vai poder pagar assim que o professor aceitar.",
              "success")
        return redirect(url_for("booking_detail", booking_id=cur.lastrowid))

    @app.route("/reservas/<int:booking_id>")
    @login_required
    def booking_detail(booking_id):
        booking = get_booking(booking_id)
        provider = payments.get_provider(app.config)
        return render_template("booking.html", b=booking,
                               reference_enabled=provider is not None,
                               sandbox=getattr(provider, "name", "") == "sandbox",
                               bank_enabled=bool(app.config["BANK_IBAN"]),
                               today=date.today().isoformat())

    def teacher_action(booking_id):
        booking = get_booking(booking_id)
        if booking["teacher_id"] != current_user()["id"]:
            abort(403)
        return booking

    def student_action(booking_id):
        booking = get_booking(booking_id)
        if booking["student_id"] != current_user()["id"]:
            abort(403)
        return booking

    def back_to(booking_id):
        return redirect(url_for("booking_detail", booking_id=booking_id))

    @app.route("/reservas/<int:booking_id>/aceitar", methods=["POST"])
    @login_required
    def booking_accept(booking_id):
        booking = teacher_action(booking_id)
        if booking["amount"] == 0:
            # Aula gratuita: fica logo confirmada
            ok = set_status(booking_id, "paga", ("pendente",), payment_method="gratuita",
                            paid_at=sql_now())
        else:
            ok = set_status(booking_id, "aceite", ("pendente",))
        flash("Reserva aceite. O aluno já pode pagar." if ok and booking["amount"]
              else "Reserva confirmada." if ok else "Esta reserva já não está pendente.",
              "success" if ok else "warning")
        return back_to(booking_id)

    @app.route("/reservas/<int:booking_id>/recusar", methods=["POST"])
    @login_required
    def booking_decline(booking_id):
        teacher_action(booking_id)
        ok = set_status(booking_id, "recusada", ("pendente",),
                        note=request.form.get("note", "").strip()[:500])
        flash("Reserva recusada." if ok else "Esta reserva já não está pendente.",
              "info" if ok else "warning")
        return back_to(booking_id)

    @app.route("/reservas/<int:booking_id>/cancelar", methods=["POST"])
    @login_required
    def booking_cancel(booking_id):
        student_action(booking_id)
        ok = set_status(booking_id, "cancelada", ("pendente", "aceite"),
                        note="Cancelada pelo aluno.")
        flash("Reserva cancelada." if ok else
              "Uma reserva já paga só pode ser cancelada pelo apoio ao cliente.",
              "info" if ok else "warning")
        return back_to(booking_id)

    @app.route("/reservas/<int:booking_id>/concluir", methods=["POST"])
    @login_required
    def booking_complete(booking_id):
        booking = get_booking(booking_id)
        if booking["lesson_date"] > date.today().isoformat():
            flash("Só pode marcar a aula como concluída depois da data da aula.", "warning")
        elif set_status(booking_id, "concluida", ("paga",)):
            flash("Aula marcada como concluída. Obrigado!", "success")
        return back_to(booking_id)

    @app.route("/reservas/<int:booking_id>/referencia", methods=["POST"])
    @login_required
    def booking_reference(booking_id):
        booking = student_action(booking_id)
        provider = payments.get_provider(app.config)
        if booking["status"] != "aceite" or provider is None:
            abort(400, "Não é possível gerar uma referência para esta reserva.")
        if booking["payment_reference"] and booking["payment_expires"] >= date.today().isoformat():
            return back_to(booking_id)
        try:
            ref = provider.create_reference(
                booking_id, booking["amount"],
                callback_url=url_for("proxypay_webhook", _external=True))
        except payments.PaymentError as e:
            app.logger.error("Falha ao gerar referência: %s", e)
            flash("Não foi possível gerar a referência agora. Tente novamente dentro de "
                  "alguns minutos.", "danger")
            return back_to(booking_id)
        db = get_db()
        db.execute("""UPDATE bookings SET payment_method = 'referencia', payment_entity = ?,
                      payment_reference = ?, payment_expires = ?, updated_at = CURRENT_TIMESTAMP
                      WHERE id = ?""", (ref["entity"], ref["reference"], ref["expires"], booking_id))
        db.commit()
        return back_to(booking_id)

    @app.route("/reservas/<int:booking_id>/simular-pagamento", methods=["POST"])
    @login_required
    def booking_simulate(booking_id):
        student_action(booking_id)
        provider = payments.get_provider(app.config)
        if getattr(provider, "name", "") != "sandbox":
            abort(404)
        if mark_paid(booking_id, "referencia"):
            flash("Pagamento simulado com sucesso (modo de testes).", "success")
        return back_to(booking_id)

    @app.route("/reservas/<int:booking_id>/comprovativo", methods=["POST"])
    @login_required
    def booking_proof(booking_id):
        booking = student_action(booking_id)
        if booking["status"] != "aceite" or not app.config["BANK_IBAN"]:
            abort(400, "Esta reserva não aceita comprovativos.")
        try:
            stored, original = save_attachment(request.files.get("proof"), PROOF_EXTENSIONS)
        except ValueError:
            flash("Envie o comprovativo em PDF ou imagem (PNG/JPG).", "danger")
            return back_to(booking_id)
        if not stored:
            flash("Escolha o ficheiro do comprovativo.", "danger")
            return back_to(booking_id)
        remove_upload(booking["proof_file"])
        db = get_db()
        db.execute("""UPDATE bookings SET payment_method = 'transferencia', proof_file = ?,
                      proof_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                   (stored, original, booking_id))
        db.commit()
        flash("Comprovativo recebido. Vamos confirmar o pagamento em até 24 horas úteis.",
              "success")
        return back_to(booking_id)

    @app.route("/reservas/<int:booking_id>/comprovativo")
    @login_required
    def booking_proof_download(booking_id):
        booking = get_booking(booking_id)
        if not booking["proof_file"] or current_user()["id"] == booking["teacher_id"]:
            abort(404)
        return send_from_directory(app.config["UPLOAD_FOLDER"], booking["proof_file"],
                                   as_attachment=True, download_name=booking["proof_name"])

    @app.route("/pagamentos/proxypay/webhook", methods=["POST"])
    def proxypay_webhook():
        raw = request.get_data()
        if not payments.verify_proxypay_signature(raw, request.headers.get("X-Signature"),
                                                  app.config["PROXYPAY_API_KEY"]):
            abort(400, "Assinatura inválida.")
        data = request.get_json(silent=True) or {}
        reference = str(data.get("reference_id", ""))
        try:
            amount = round(float(data.get("amount")))
        except (TypeError, ValueError):
            abort(400, "Montante inválido.")
        db = get_db()
        booking = db.execute("SELECT * FROM bookings WHERE payment_reference = ?",
                             (reference,)).fetchone()
        try:
            db.execute("""INSERT INTO payment_events (provider, event_id, booking_id, amount, payload)
                          VALUES ('proxypay', ?, ?, ?, ?)""",
                       (str(data.get("id", reference)), booking["id"] if booking else None,
                        amount, raw.decode(errors="replace")))
            db.commit()
        except sqlite3.IntegrityError:
            return {"status": "duplicado"}, 200
        if booking is None:
            app.logger.warning("Pagamento ProxyPay sem reserva: referência %s", reference)
        elif amount < booking["amount"]:
            app.logger.warning("Pagamento abaixo do valor na reserva %s", booking["id"])
        else:
            mark_paid(booking["id"], "referencia")
        return {"status": "ok"}, 200


def register_admin(app):

    @app.route("/admin")
    @admin_required
    def admin():
        db = get_db()
        proofs = db.execute(BOOKING_SELECT + """
            WHERE b.status = 'aceite' AND b.proof_file IS NOT NULL ORDER BY b.updated_at""").fetchall()
        payouts = db.execute(BOOKING_SELECT + """
            WHERE b.status = 'concluida' AND b.payout_status = 'por_pagar' AND b.teacher_amount > 0
            ORDER BY b.lesson_date""").fetchall()
        recent = db.execute(BOOKING_SELECT + " ORDER BY b.id DESC LIMIT 30").fetchall()
        totals = db.execute("""
            SELECT COALESCE(SUM(amount), 0), COALESCE(SUM(commission), 0), COUNT(*)
            FROM bookings WHERE status IN ('paga', 'concluida')""").fetchone()
        return render_template("admin.html", proofs=proofs, payouts=payouts, recent=recent,
                               totals=totals)

    @app.route("/admin/reservas/<int:booking_id>/confirmar", methods=["POST"])
    @admin_required
    def admin_confirm(booking_id):
        ok = mark_paid(booking_id, "transferencia")
        flash("Pagamento confirmado." if ok else "A reserva não estava a aguardar pagamento.",
              "success" if ok else "warning")
        return redirect(url_for("admin"))

    @app.route("/admin/reservas/<int:booking_id>/repasse", methods=["POST"])
    @admin_required
    def admin_payout(booking_id):
        db = get_db()
        db.execute("""UPDATE bookings SET payout_status = 'pago', payout_at = CURRENT_TIMESTAMP
                      WHERE id = ? AND status = 'concluida'""", (booking_id,))
        db.commit()
        flash("Pagamento ao professor registado.", "success")
        return redirect(url_for("admin"))

    @app.route("/admin/reservas/<int:booking_id>/cancelar", methods=["POST"])
    @admin_required
    def admin_cancel(booking_id):
        set_status(booking_id, "cancelada", ("pendente", "aceite", "paga"),
                   note=request.form.get("note", "").strip()[:500] or "Cancelada pelo apoio.")
        flash("Reserva cancelada. Se já estava paga, faça o reembolso ao aluno.", "info")
        return redirect(url_for("admin"))

    @app.cli.command("criar-admin")
    @click.argument("email")
    def create_admin(email):
        """Promove uma conta existente a administrador."""
        db = get_db()
        if db.execute("UPDATE users SET role = 'admin' WHERE email = ?",
                      (email.lower(),)).rowcount:
            db.commit()
            click.echo(f"{email} é agora administrador.")
        else:
            click.echo("Conta não encontrada.")


def remove_upload(stored):
    if stored:
        try:
            os.remove(os.path.join(current_app.config["UPLOAD_FOLDER"], stored))
        except OSError:
            pass


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
