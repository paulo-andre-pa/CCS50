import io
import os
import sys

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
        "modality": "Presencial", "province": "Luanda", "price": "15000",
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


def test_teacher_publishes_and_student_enrolls(app, client):
    register(client, "professor")
    r = client.post("/publicar", data=offer(), follow_redirects=True)
    assert b"Explica" in r.data and "15.000 Kz".encode() in r.data
    client.post("/sair")

    student = app.test_client()
    register(student, "aluno")
    r = student.post("/conteudos/1/inscrever", data={"message": "Sábados de manhã"},
                     follow_redirects=True)
    assert "Inscrição feita".encode() in r.data
    student.post("/conteudos/1/comentar", data={"body": "Qual é o horário?"})

    client.post("/entrar", data={"email": "professor@exemplo.ao", "password": "segredo123"})
    r = client.get("/painel")
    assert b"aluno@exemplo.ao" in r.data and "Sábados de manhã".encode() in r.data
    assert "Qual é o horário?".encode() in client.get("/conteudos/1").data


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
