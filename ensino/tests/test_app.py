import hashlib
import hmac
import io
import json
import os
import sqlite3
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app  # noqa: E402


@pytest.fixture
def app(tmp_path):
    return create_app({
        "DATABASE": str(tmp_path / "test.db"),
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        "TESTING": True,
        "TESTING_NO_CSRF": True,
        "PAYMENTS_SANDBOX": True,
        "PROXYPAY_API_KEY": "",
        "BANK_NAME": "Banco Teste", "BANK_HOLDER": "Ekulihiso, Lda",
        "BANK_IBAN": "AO06000000000000000000000",
        "COMMISSION_PERCENT": 10,
    })


@pytest.fixture
def client(app):
    return app.test_client()


def register(client, role="aluno", email=None, **extra):
    data = {
        "name": f"Teste {role.title()}", "email": email or f"{role}@exemplo.ao",
        "password": "segredo123", "confirmation": "segredo123",
        "role": role, "province": "Luanda",
        "level": "II Ciclo do Secundário (10ª–13ª classe)",
    }
    data.update(extra)
    return client.post("/registar", data=data, follow_redirects=True)


def offer(**extra):
    data = {
        "kind": "explicacao", "discipline_id": "2", "title": "Explicação de Matemática",
        "summary": "Aulas de reforço para a 12ª classe.",
        "body": "Programa completo: funções, limites, derivadas e preparação para exames.",
        "level": "II Ciclo do Secundário (10ª–13ª classe)",
        "modality": "Presencial", "province": "Luanda", "price": "3000",
    }
    data.update(extra)
    return data


def test_pages_load(client):
    for path in ["/", "/conteudos", "/disciplinas", "/professores", "/sobre",
                 "/registar", "/entrar"]:
        assert client.get(path).status_code == 200, path


def test_register_login_logout(client):
    r = register(client)
    assert "Bem-vindo".encode() in r.data
    client.post("/sair")
    r = client.post("/entrar", data={"email": "aluno@exemplo.ao", "password": "errada"})
    assert r.status_code == 401
    r = client.post("/entrar", data={"email": "aluno@exemplo.ao", "password": "segredo123"},
                    follow_redirects=True)
    assert "Painel".encode() in r.data or "inscrições".encode() in r.data


def test_duplicate_email_rejected(client):
    register(client)
    client.post("/sair")
    r = register(client)
    assert "Já existe uma conta".encode() in r.data


def test_student_cannot_publish(client):
    register(client)
    r = client.post("/publicar", data=offer(), follow_redirects=True)
    assert "Apenas professores".encode() in r.data


def tomorrow():
    return (date.today() + timedelta(days=1)).isoformat()


def booking_form(**extra):
    data = {"lesson_date": tomorrow(), "lesson_time": "15:00", "hours": "2",
            "message": "Sábados de manhã"}
    data.update(extra)
    return data


def setup_booking(app, client, **post_extra):
    """Professor publica, aluno reserva. Devolve o cliente do aluno."""
    register(client, "professor")
    client.post("/publicar", data=offer(**post_extra))
    student = app.test_client()
    register(student, "aluno")
    student.post("/conteudos/1/reservar", data=booking_form())
    return student


def query(app, sql, *args):
    con = sqlite3.connect(app.config["DATABASE"])
    con.row_factory = sqlite3.Row
    row = con.execute(sql, args).fetchone()
    con.commit()
    con.close()
    return row


def test_booking_full_flow(app, client):
    student = setup_booking(app, client)
    b = query(app, "SELECT * FROM bookings WHERE id = 1")
    assert b["status"] == "pendente" and b["amount"] == 6000
    assert b["commission"] == 600 and b["teacher_amount"] == 5400

    # O professor vê o pedido, mas ainda não os contactos do aluno
    page = client.get("/reservas/1").data
    assert "Sábados de manhã".encode() in page and b"aluno@exemplo.ao" not in page
    client.post("/reservas/1/aceitar")
    assert query(app, "SELECT status FROM bookings")["status"] == "aceite"

    # O aluno gera a referência e paga (modo de testes)
    student.post("/reservas/1/referencia")
    b = query(app, "SELECT * FROM bookings WHERE id = 1")
    assert b["payment_reference"] and b["payment_method"] == "referencia"
    assert b["payment_reference"].encode() in student.get("/reservas/1").data
    student.post("/reservas/1/simular-pagamento")
    assert query(app, "SELECT status FROM bookings")["status"] == "paga"

    # Depois de pago, cada um vê os contactos do outro
    assert b"professor@exemplo.ao" in student.get("/reservas/1").data
    assert b"aluno@exemplo.ao" in client.get("/reservas/1").data

    # Aula concluída -> repasse ao professor pelo administrador
    query(app, "UPDATE bookings SET lesson_date = ?", date.today().isoformat())
    student.post("/reservas/1/concluir")
    assert query(app, "SELECT status FROM bookings")["status"] == "concluida"
    admin = app.test_client()
    register(admin, "aluno", email="admin@exemplo.ao")
    query(app, "UPDATE users SET role = 'admin' WHERE email = 'admin@exemplo.ao'")
    assert "5.400 Kz".encode() in admin.get("/admin").data
    admin.post("/admin/reservas/1/repasse")
    assert query(app, "SELECT payout_status FROM bookings")["payout_status"] == "pago"


def test_cannot_pay_before_teacher_accepts(app, client):
    student = setup_booking(app, client)
    assert student.post("/reservas/1/referencia").status_code == 400
    student.post("/reservas/1/simular-pagamento")
    assert query(app, "SELECT status FROM bookings")["status"] == "pendente"


def test_first_lesson_free(app, client):
    register(client, "professor")
    client.post("/publicar", data=offer(first_lesson_free="1"))
    student = app.test_client()
    register(student, "aluno")
    student.post("/conteudos/1/reservar", data=booking_form(hours="1"))
    b = query(app, "SELECT * FROM bookings WHERE id = 1")
    assert b["amount"] == 0 and b["free_hours"] == 1
    client.post("/reservas/1/aceitar")
    assert query(app, "SELECT status FROM bookings")["status"] == "paga"
    # A segunda reserva com o mesmo professor já é paga
    student.post("/conteudos/1/reservar", data=booking_form(hours="1"))
    assert query(app, "SELECT amount FROM bookings WHERE id = 2")["amount"] == 3000


def test_booking_validation_and_permissions(app, client):
    student = setup_booking(app, client)
    past = (date.today() - timedelta(days=1)).isoformat()
    r = student.post("/conteudos/1/reservar", data=booking_form(lesson_date=past),
                     follow_redirects=True)
    assert "Escolha uma data".encode() in r.data
    assert client.post("/conteudos/1/reservar", data=booking_form(),
                       follow_redirects=True).status_code == 200
    assert query(app, "SELECT COUNT(*) AS n FROM bookings")["n"] == 1
    outsider = app.test_client()
    register(outsider, "aluno", email="outro@exemplo.ao")
    assert outsider.get("/reservas/1").status_code == 403
    assert student.post("/reservas/1/aceitar").status_code == 403


def test_ad_requires_price(client):
    register(client, "professor")
    r = client.post("/publicar", data=offer(price=""))
    assert r.status_code == 422 and "preço por hora".encode() in r.data


def test_bank_transfer_proof_confirmed_by_admin(app, client):
    student = setup_booking(app, client)
    client.post("/reservas/1/aceitar")
    student.post("/reservas/1/comprovativo", data={"proof": (io.BytesIO(b"%PDF"), "talao.pdf")},
                 content_type="multipart/form-data")
    assert query(app, "SELECT payment_method FROM bookings")["payment_method"] == "transferencia"
    admin = app.test_client()
    register(admin, "aluno", email="admin@exemplo.ao")
    query(app, "UPDATE users SET role = 'admin' WHERE email = 'admin@exemplo.ao'")
    assert b"talao.pdf" in admin.get("/admin").data
    admin.post("/admin/reservas/1/confirmar")
    assert query(app, "SELECT status FROM bookings")["status"] == "paga"
    assert student.get("/admin").status_code == 403


def test_proxypay_webhook(app, client):
    setup_booking(app, client)
    client.post("/reservas/1/aceitar")
    query(app, "UPDATE bookings SET payment_reference = '900123456'")
    app.config["PROXYPAY_API_KEY"] = "chave-secreta"
    body = json.dumps({"id": 77, "reference_id": 900123456, "amount": "6000.00",
                       "custom_fields": {"booking_id": "1"}}).encode()
    sig = hmac.new(b"chave-secreta", body, hashlib.sha256).hexdigest()
    hook = "/pagamentos/proxypay/webhook"
    headers = {"Content-Type": "application/json"}
    assert client.post(hook, data=body, headers={**headers, "X-Signature": "falsa"}).status_code == 400
    assert query(app, "SELECT status FROM bookings")["status"] == "aceite"
    r = client.post(hook, data=body, headers={**headers, "X-Signature": sig})
    assert r.status_code == 200 and query(app, "SELECT status FROM bookings")["status"] == "paga"
    assert client.post(hook, data=body, headers={**headers, "X-Signature": sig}).json["status"] == "duplicado"


def test_filters_and_search(client):
    register(client, "professor")
    client.post("/publicar", data=offer())
    client.post("/publicar", data=offer(kind="conteudo", title="Resumo de fotossíntese",
                                        discipline_id="5"))
    r = client.get("/conteudos?tipo=conteudo")
    assert "fotossíntese".encode() in r.data and b"Explica\xc3\xa7\xc3\xa3o de Matem" not in r.data
    r = client.get("/conteudos?q=fotoss")
    assert b"1 resultado" in r.data
    r = client.get("/conteudos?disciplina=matematica")
    assert "Explicação de Matemática".encode() in r.data


def test_only_owner_can_edit_or_delete(app, client):
    register(client, "professor")
    client.post("/publicar", data=offer())
    other = app.test_client()
    register(other, "professor", email="outro@exemplo.ao")
    assert other.get("/conteudos/1/editar").status_code == 403
    assert other.post("/conteudos/1/apagar").status_code == 403
    r = client.post("/conteudos/1/apagar", follow_redirects=True)
    assert "Publicação apagada".encode() in r.data
    assert client.get("/conteudos/1").status_code == 404


def test_attachment_upload_and_download(client):
    register(client, "professor")
    data = offer(kind="conteudo")
    data["attachment"] = (io.BytesIO(b"%PDF-1.4 teste"), "ficha.pdf")
    client.post("/publicar", data=data, content_type="multipart/form-data")
    r = client.get("/ficheiros/1")
    assert r.status_code == 200 and r.data.startswith(b"%PDF")

    bad = offer(kind="conteudo")
    bad["attachment"] = (io.BytesIO(b"x"), "virus.exe")
    r = client.post("/publicar", data=bad, content_type="multipart/form-data")
    assert r.status_code == 422


def test_csrf_enforced(tmp_path):
    app = create_app({"DATABASE": str(tmp_path / "c.db"),
                      "UPLOAD_FOLDER": str(tmp_path / "u"), "TESTING": True})
    r = app.test_client().post("/entrar", data={"email": "a@b.ao", "password": "x"})
    assert r.status_code == 400


def test_open_redirect_blocked(client):
    register(client)
    client.post("/sair")
    r = client.post("/entrar?next=//evil.com", data={"email": "aluno@exemplo.ao",
                                                     "password": "segredo123"})
    assert r.headers["Location"].endswith("/painel")
