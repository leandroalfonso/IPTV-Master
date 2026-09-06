# IPTV Admin

Painel administrativo de usuários para uma aplicação IPTV, criado com Python 3, Flask, Flask-Login, Flask-SQLAlchemy e SQLite.

## Requisitos

- Python 3.10+
- pip

## Instalação

```bash
cd iptv_admin
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edite `.env` e troque `SECRET_KEY`, `ADMIN_USERNAME` e `ADMIN_PASSWORD`. O administrador inicial é criado automaticamente na primeira execução quando essas variáveis estão preenchidas. A senha nunca é salva em texto puro.

## Executar

```bash
python app.py
```

Acesse `http://127.0.0.1:5000/login` e use o administrador configurado no `.env`. O SQLite é criado automaticamente em `instance/database.db`, com as tabelas `admins`, `users`, `user_devices` e `access_logs`.

## Fluxo administrativo

1. Entre no painel.
2. Abra **Adicionar usuário**.
3. Informe nome, usuário, senha, dias de acesso e limite de dispositivos.
4. O sistema grava `activated_at`, calcula `expires_at` e gera um token criptográfico.
5. Em detalhes, é possível renovar, bloquear/ativar, resetar senha, excluir e regenerar token.
6. A renovação soma dias à expiração atual se ainda estiver ativo; se expirado, começa em agora.

Os estados são calculados dinamicamente pela data: `ATIVO` (>7 dias), `EXPIRANDO` (1–7), `EXPIRADO` (0 ou menos) e `BLOQUEADO` (desativado manualmente).

## Login do aplicativo

A tela de acesso do usuário final fica separada do painel administrativo:

- `GET /app/login` — tela de login do aplicativo.
- `POST /app/login` — valida usuário, senha, bloqueio e validade.
- `GET /app` — área protegida do usuário autenticado.
- `POST /app/logout` — encerra a sessão do aplicativo.

O usuário final entra com o `username` e a senha cadastrados em **Adicionar usuário**. Em ambiente integrado, após a validação o painel emite uma autorização temporária assinada e redireciona para o StreamVault existente (por padrão em `http://192.168.0.5:5001`), preservando a interface IPTV real, canais, filmes, séries e player. O StreamVault rejeita acesso direto sem essa autorização. A sessão do aplicativo é independente do Flask-Login administrativo; mesmo autenticado no aplicativo, o usuário não recebe acesso às rotas `/admin/*`. Usuários bloqueados ou expirados recebem uma mensagem de acesso negado. A API `/api/auth` continua disponível para clientes nativos/RPA que utilizam também o `access_token`.

## API RPA

Validação de acesso:

```bash
curl -X POST http://127.0.0.1:5000/api/auth \
  -H 'Content-Type: application/json' \
  -d '{"username":"joao123","password":"senha-segura","access_token":"TOKEN"}'
```

Também existe `POST /api/login` e `POST /api/validate` com o mesmo contrato. Para consultar status, use:

```bash
curl 'http://127.0.0.1:5000/api/user/status?username=joao123&access_token=TOKEN'
```

A API sempre consulta o banco, confere usuário ativo, senha, token e `expires_at`. Ela nunca confia em dias enviados pelo aplicativo. Respostas de bloqueio usam `reason=blocked`; expiradas usam `reason=expired`; token incorreto usa `reason=invalid_token`.

## Segurança

- Senhas usam hash seguro do Werkzeug.
- Rotas administrativas exigem Flask-Login e administrador ativo.
- Formulários mutáveis têm token CSRF.
- Consultas usam SQLAlchemy parametrizado.
- Tokens usam `secrets.token_urlsafe`.
- Cookies de sessão são HttpOnly e SameSite=Lax.
- Eventos administrativos e tentativas da API são registrados em `access_logs`.
- O campo `user_devices` já existe para futura limitação de dispositivos.

Em produção, use HTTPS, uma `SECRET_KEY` longa e aleatória, servidor WSGI e variáveis de ambiente protegidas. Não versionar `.env` nem `instance/database.db`.
