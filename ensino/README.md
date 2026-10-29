# Ensino Ekulihiso — ensino.ekulihiso.com

Uma plataforma de ensino para Angola. Os **professores** publicam conteúdos didácticos e anunciam as disciplinas que querem ensinar (explicações). Os **alunos** inscrevem-se, estudam, descarregam materiais e tiram dúvidas.

## Funcionalidades

| Para alunos | Para professores |
|---|---|
| Conta gratuita com província e nível de ensino | Conta de professor com perfil público |
| Pesquisa e filtros por disciplina, nível, tipo e província | Anunciar disciplinas para ensinar (presencial/online, preço em Kz) |
| Conteúdos didácticos e anexos para descarregar (PDF, Word, PPT…) | Publicar conteúdos didácticos com anexos (até 10 MB) |
| Inscrição em explicações, com mensagem ao professor | Painel com os alunos inscritos e os seus contactos |
| Perguntas e comentários em cada publicação | Editar e apagar as suas publicações |
| Painel com inscrições e sugestões para o seu nível | Responder às dúvidas dos alunos |

Feita a pensar em Angola:
- As **21 províncias** e os níveis do sistema de ensino angolano (Primário, I e II Ciclo, Técnico-Profissional, Exames de Acesso, Superior).
- Preços em **Kwanzas**, explicações presenciais ou online.
- **Leve**: sem frameworks JavaScript, Bootstrap servido localmente (sem depender de CDNs), funciona bem em telemóveis e ligações 3G.
- Interface em português de Angola.

## Tecnologia

- Python 3 + [Flask](https://flask.palletsprojects.com/)
- SQLite (sem servidor de base de dados para gerir)
- Bootstrap 5 + Bootstrap Icons
- Segurança: palavras-passe com hash, protecção CSRF, cookies `HttpOnly`, validação de anexos, controlo de permissões

## Executar localmente

```bash
cd ensino
```

```bash
python3 -m venv .venv && source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

```bash
python seed.py
```

```bash
flask --app app run --debug
```

Abra http://127.0.0.1:5000. O `seed.py` é opcional e cria contas de demonstração:
- Professor: `ana@exemplo.ao` / `professor123`
- Aluno: `aluno@exemplo.ao` / `aluno1234`

### Testes

```bash
pip install pytest && python -m pytest tests
```

## Publicar em ensino.ekulihiso.com

1. **Servidor**: um VPS Linux (Ubuntu) pequeno chega para começar (1 vCPU, 1 GB RAM).
2. **DNS**: no painel do domínio `ekulihiso.com`, crie um registo `A` com o nome `ensino` a apontar para o IP do servidor.
3. **Aplicação**:
   ```bash
   git clone https://github.com/paulo-andre-pa/CCS50.git /srv/ccs50
   ```
   ```bash
   cd /srv/ccs50/ensino && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   ```
4. **Serviço systemd** (`/etc/systemd/system/ensino.service`):
   ```ini
   [Unit]
   Description=Ensino Ekulihiso
   After=network.target

   [Service]
   WorkingDirectory=/srv/ccs50/ensino
   Environment=SECRET_KEY=troque-por-uma-chave-longa-e-aleatoria
   Environment=SESSION_COOKIE_SECURE=1
   ExecStart=/srv/ccs50/ensino/.venv/bin/gunicorn -w 3 -b 127.0.0.1:8000 app:app
   Restart=always
   User=www-data

   [Install]
   WantedBy=multi-user.target
   ```
   Gere a chave com `python3 -c "import secrets; print(secrets.token_hex(32))"`, depois active o serviço com `systemctl enable --now ensino`.
5. **Nginx** (`/etc/nginx/sites-available/ensino`):
   ```nginx
   server {
       server_name ensino.ekulihiso.com;
       client_max_body_size 10M;

       location /static/ {
           alias /srv/ccs50/ensino/static/;
           expires 30d;
       }
       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```
6. **HTTPS** gratuito com Let's Encrypt: `certbot --nginx -d ensino.ekulihiso.com`.

### Variáveis de ambiente

| Variável | Descrição |
|---|---|
| `SECRET_KEY` | **Obrigatória em produção.** Chave para assinar as sessões. |
| `DATABASE` | Caminho da base SQLite (por omissão `instance/ensino.db`). |
| `UPLOAD_FOLDER` | Pasta dos anexos (por omissão `instance/uploads`). |
| `SESSION_COOKIE_SECURE` | `1` quando o site corre em HTTPS. |

Faça cópias de segurança regulares da pasta `instance/` (base de dados e anexos).

## Estrutura

```
ensino/
├── app.py            # Aplicação Flask (rotas, autenticação, validação)
├── schema.sql        # Tabelas: users, disciplines, posts, enrollments, comments
├── seed.py           # Dados de demonstração
├── templates/        # Páginas HTML (Jinja)
├── static/           # CSS, ícone e Bootstrap local
└── tests/            # Testes automáticos (pytest)
```

## Próximos passos sugeridos

- Recuperação de palavra-passe por email ou SMS.
- Pagamentos de explicações via Multicaixa Express / referência bancária.
- Avaliações dos professores pelos alunos.
- Painel de administração para moderar conteúdos.
- Migrar para PostgreSQL quando houver muitos utilizadores em simultâneo.
