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
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS disciplines (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE
);

-- kind: 'conteudo' (material didáctico) ou 'explicacao' (oferta para ensinar uma disciplina)
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
    attachment    TEXT,
    attachment_name TEXT,
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS enrollments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    message    TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (student_id, post_id)
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
