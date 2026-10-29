"""Popula a base de dados com dados de demonstração: python seed.py"""

from werkzeug.security import generate_password_hash

from app import create_app, get_db

TEACHERS = [
    ("Ana Kiluanji", "ana@exemplo.ao", "Luanda", "Licenciada em Matemática pela UAN, 8 anos a leccionar no II Ciclo."),
    ("Domingos Tchiyevo", "domingos@exemplo.ao", "Huambo", "Professor de Biologia e Química no Huambo."),
    ("Esperança Muteka", "esperanca@exemplo.ao", "Benguela", "Professora de Inglês e Português, certificada pelo British Council."),
]

POSTS = [
    (0, "Matemática", "explicacao", "Explicações de Matemática — 12ª classe e exames de acesso",
     "Preparação intensiva para os exames de acesso à universidade.",
     "Aulas em grupos pequenos (máx. 6 alunos) no Kilamba.\n\nPrograma:\n- Funções e gráficos\n- Limites e derivadas\n- Trigonometria\n- Resolução de exames anteriores",
     "Preparação para Exames de Acesso", "Presencial e Online", "Luanda", 4000),
    (0, "Matemática", "conteudo", "Equações do 2º grau — resumo e exercícios resolvidos",
     "Fórmula resolvente, discriminante e 10 exercícios resolvidos passo a passo.",
     "Uma equação do 2º grau tem a forma ax² + bx + c = 0, com a ≠ 0.\n\nDiscriminante: Δ = b² − 4ac\n- Δ > 0: duas soluções reais\n- Δ = 0: uma solução\n- Δ < 0: sem soluções reais\n\nFórmula resolvente: x = (−b ± √Δ) / 2a",
     "I Ciclo do Secundário (7ª–9ª classe)", None, None, None),
    (1, "Biologia", "conteudo", "A fotossíntese explicada de forma simples",
     "Como as plantas transformam luz solar em energia — com esquemas.",
     "A fotossíntese ocorre nos cloroplastos.\n\n6CO₂ + 6H₂O + luz → C₆H₁₂O₆ + 6O₂\n\nFase clara: nos tilacóides.\nFase escura (ciclo de Calvin): no estroma.",
     "II Ciclo do Secundário (10ª–13ª classe)", None, None, None),
    (1, "Química", "explicacao", "Aulas de Química no Huambo",
     "Reforço escolar em Química para o II Ciclo, ao fim-de-semana.",
     "Aulas aos sábados no centro da cidade do Huambo. Estequiometria, ligações químicas, química orgânica e laboratório.",
     "II Ciclo do Secundário (10ª–13ª classe)", "Presencial", "Huambo", 2500),
    (2, "Inglês", "explicacao", "Inglês online para todos os níveis",
     "Conversação, gramática e preparação para certificações — por videochamada.",
     "Aulas individuais ou em grupo via Zoom ou WhatsApp. Horários flexíveis, inclusive à noite.",
     "Formação Profissional / Adultos", "Online", None, 3500),
]

app = create_app()
with app.app_context():
    db = get_db()
    ids = []
    for name, email, prov, bio in TEACHERS:
        db.execute("INSERT OR IGNORE INTO users (name, email, password_hash, role, province, bio) "
                   "VALUES (?, ?, ?, 'professor', ?, ?)",
                   (name, email, generate_password_hash("professor123"), prov, bio))
        ids.append(db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0])
    db.execute("INSERT OR IGNORE INTO users (name, email, password_hash, role, province, level) "
               "VALUES ('Joaquim Ndala', 'aluno@exemplo.ao', ?, 'aluno', 'Luanda', ?)",
               (generate_password_hash("aluno1234"), "II Ciclo do Secundário (10ª–13ª classe)"))
    db.execute("INSERT OR IGNORE INTO users (name, email, password_hash, role, province) "
               "VALUES ('Administração', 'admin@exemplo.ao', ?, 'admin', 'Luanda')",
               (generate_password_hash("admin1234"),))
    db.execute("UPDATE users SET iban = 'AO06004000001234567890123' WHERE email = 'ana@exemplo.ao'")
    if not db.execute("SELECT 1 FROM posts").fetchone():
        for t, disc, kind, title, summary, body, level, mod, prov, price in POSTS:
            did = db.execute("SELECT id FROM disciplines WHERE name = ?", (disc,)).fetchone()[0]
            db.execute("INSERT INTO posts (teacher_id, discipline_id, kind, title, summary, body, "
                       "level, modality, province, price, first_lesson_free) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (ids[t], did, kind, title, summary, body, level, mod, prov, price,
                        1 if t == 0 and kind == "explicacao" else 0))
    db.commit()
    print("Dados de demonstração criados.")
    print("Professor: ana@exemplo.ao / professor123 · Aluno: aluno@exemplo.ao / aluno1234 · "
          "Admin: admin@exemplo.ao / admin1234")
