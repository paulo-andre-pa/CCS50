-- Esquema da base de dados do Ensino Ekulihiso

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK (role IN ('aluno', 'professor', 'admin')),
    province      TEXT    NOT NULL,
    level         TEXT,
    bio           TEXT    NOT NULL DEFAULT '',
    phone         TEXT    NOT NULL DEFAULT '',
    iban          TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS disciplines (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE
);

-- kind: 'conteudo' (material didáctico) ou 'explicacao' (anúncio de aulas; price = Kz por hora)
CREATE TABLE IF NOT EXISTS posts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    discipline_id INTEGER NOT NULL REFERENCES disciplines(id),
    kind          TEXT    NOT NULL CHECK (kind IN ('conteudo', 'explicacao')),
    title         TEXT    NOT NULL,
    summary       TEXT    NOT NULL,
    body          TEXT    NOT NULL,
    level         TEXT    NOT NULL,
    modality      TEXT,
    province      TEXT,
    price         INTEGER,
    first_lesson_free INTEGER NOT NULL DEFAULT 0,
    attachment    TEXT,
    attachment_name TEXT,
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Reservas de aulas. Fluxo: pendente -> aceite -> paga -> concluida
-- (ou recusada / cancelada). Os valores são em Kwanzas inteiros.
CREATE TABLE IF NOT EXISTS bookings (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id           INTEGER REFERENCES posts(id) ON DELETE SET NULL,
    post_title        TEXT    NOT NULL,
    student_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    teacher_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lesson_date       TEXT    NOT NULL,
    lesson_time       TEXT    NOT NULL,
    hours             INTEGER NOT NULL CHECK (hours BETWEEN 1 AND 10),
    modality          TEXT    NOT NULL,
    message           TEXT    NOT NULL DEFAULT '',
    price_per_hour    INTEGER NOT NULL,
    free_hours        INTEGER NOT NULL DEFAULT 0,
    amount            INTEGER NOT NULL,
    commission        INTEGER NOT NULL,
    teacher_amount    INTEGER NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'pendente'
                      CHECK (status IN ('pendente', 'aceite', 'paga', 'concluida', 'recusada', 'cancelada')),
    status_note       TEXT    NOT NULL DEFAULT '',
    payment_method    TEXT,
    payment_entity    TEXT,
    payment_reference TEXT    UNIQUE,
    payment_expires   TEXT,
    proof_file        TEXT,
    proof_name        TEXT,
    paid_at           TEXT,
    payout_status     TEXT    NOT NULL DEFAULT 'por_pagar' CHECK (payout_status IN ('por_pagar', 'pago')),
    payout_at         TEXT,
    created_at        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Registo de notificações de pagamento (auditoria e protecção contra duplicados)
CREATE TABLE IF NOT EXISTS payment_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    provider   TEXT    NOT NULL,
    event_id   TEXT    NOT NULL,
    booking_id INTEGER REFERENCES bookings(id) ON DELETE SET NULL,
    amount     INTEGER,
    payload    TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (provider, event_id)
);

CREATE TABLE IF NOT EXISTS comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body       TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_posts_discipline ON posts(discipline_id);
CREATE INDEX IF NOT EXISTS idx_posts_teacher ON posts(teacher_id);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id);
CREATE INDEX IF NOT EXISTS idx_bookings_student ON bookings(student_id);
CREATE INDEX IF NOT EXISTS idx_bookings_teacher ON bookings(teacher_id);
