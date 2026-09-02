# StreamVault — IPTV pessoal estilo streaming

StreamVault é um sistema de streaming IPTV **pessoal**, com visual inspirado em
plataformas como Netflix e Prime Video, mas com identidade própria. Ele lê a sua
própria lista IPTV (M3U), organiza canais, filmes e séries, e exibe tudo em uma
interface moderna e responsiva.

Construído com **Flask + SQLite** no backend e **HTML5/CSS3/JS puro (Bootstrap 5.3)**
no frontend.

---

## Funcionalidades

- 📺 TV ao vivo, 🎬 Filmes e 📚 Séries em páginas separadas
- 🔎 Pesquisa global dinâmica (canais / filmes / séries)
- ⭐ Favoritos ("Minha Lista") persistidos em SQLite
- ⏯️ "Continuar assistindo" com progresso salvo
- 🎞️ Player funcional para **HLS (.m3u8)** e **MP4** (com hls.js quando necessário)
- 🗂️ Categorias e filtros (A-Z, etc.)
- 🔄 Atualização da lista sem mexer no frontend
- 💾 Cache da lista (configurável em minutos)
- ⚙️ Página de configurações (URL da lista, status, limpeza de cache)
- 🔒 URL/senha da IPTV **nunca** expostas ao navegador (só no `.env` do servidor)
- 📱 Totalmente responsivo (desktop, tablet, celular)

---

## 1. Pré-requisitos

- Python 3.9+ instalado. Baixe em https://www.python.org/downloads/

## 2. Criar ambiente virtual

```bash
cd streamvault
python -m venv venv
```

Ativar:

```bash
# Linux / macOS
source venv/bin/activate

# Windows (PowerShell)
venv\Scripts\Activate.ps1
```

## 3. Instalar dependências

```bash
pip install -r requirements.txt
```

## 4. Configurar o `.env`

Copie o exemplo e edite:

```bash
cp .env.example .env
```

Edite o `.env` e defina a sua lista:

```ini
SECRET_KEY=mude-para-algo-unico
IPTV_TYPE=m3u
IPTV_M3U_URL=https://exemplo.com/minha-lista.m3u
IPTV_CACHE_MINUTES=30
```

> Também aceita **arquivo local**: `IPTV_M3U_URL=data/minha-lista.m3u`
> (coloque o arquivo em `data/`).

⚠️ A URL da lista **não** aparece no código nem no frontend — fica apenas no
servidor.

## 5. Executar

```bash
python app.py
```

Acesse: **http://127.0.0.1:5000**

Na primeira execução, o sistema baixa e processa a lista automaticamente.

## 6. Configurar a lista IPTV

- Pela interface: menu ⚙️ **Configurações** → cole a URL → "Salvar" → "Atualizar lista".
- Pelo `.env`: altere `IPTV_M3U_URL` e reinicie o servidor.

## 7. Atualizar a lista

Botão **"Atualizar lista"** em Configurações, ou endpoint:

```bash
curl -X POST http://127.0.0.1:5000/api/iptv/refresh
```

Respeita o cache (`IPTV_CACHE_MINUTES`); "Atualizar agora" força o refresh.

## 8. Solução de problemas do player

| Sintoma | Causa provável | Solução |
|---|---|---|
| Vídeo não carrega | Stream offline / bloqueado por geo | Teste a URL em outro player; verifique CORS/rede |
| "Não foi possível reproduzir" | Formato não suportado | Use HLS/MP4; o player usa hls.js automaticamente |
| Travamentos em canal ao vivo | Stream instável | O player tenta reconectar sozinho (hls.js) |
| Lista vazia | URL errada ou lista no formato não reconhecido | Confira o `.env` e os logs do terminal |

---

## Estrutura

```
streamvault/
├── app.py                # entrypoint Flask
├── requirements.txt
├── .env.example
├── data/                # banco SQLite e lista local
├── app/
│   ├── __init__.py      # create_app()
│   ├── config.py        # configurações (.env)
│   ├── database.py      # SQLite (CRUD, índices)
│   ├── models.py        # Content (dataclass normalizado)
│   ├── iptv.py          # parser M3U + Xtream (modular)
│   ├── routes.py        # páginas + API REST
│   ├── templates/       # Jinja2 (base, index, canais, ...)
│   └── static/
│       ├── css/style.css
│       └── js/{app,player,config}.js
└── README.md
```

## API REST (interna)

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/api/contents` | conteúdos (filtros type/category/q/sort/page/limit) |
| GET | `/api/live` | canais ao vivo |
| GET | `/api/movies` | filmes |
| GET | `/api/series` | lista de séries |
| GET | `/api/categories` | categorias |
| GET | `/api/search?q=` | pesquisa global |
| GET/POST | `/api/favorites` | favoritos |
| DELETE | `/api/favorites/<id>` | remove favorito |
| GET/POST | `/api/history` | histórico ("continuar assistindo") |
| POST | `/api/iptv/refresh` | atualiza a lista |
| POST | `/api/iptv/clear` | limpa o cache |
| GET | `/api/status` | status geral |

## Notas de segurança

- Nunca comite o `.env` real.
- Em VPS, defina `HOST=0.0.0.0` e use um proxy reverso (nginx) + HTTPS.
- O backend é quem acessa a fonte IPTV — o frontend nunca vê a URL.

## Licença

Uso pessoal.
# IPTV-Master
