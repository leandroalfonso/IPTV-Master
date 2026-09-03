"""Camada de acesso a dados (SQLite).

Centraliza a criação do banco, índices e todas as operações CRUD.
Usa consultas parametrizadas em todo lugar para evitar SQL injection.
"""

import os
import sqlite3
import json
from datetime import datetime, timezone
from typing import Optional

from . import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.Config.DATABASE_PATH), exist_ok=True)
    # timeout: espera em vez de lançar "database is locked" sob concorrência
    # (ex.: carga da lista + leituras simultâneas das rotas/proxy).
    conn = sqlite3.connect(config.Config.DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL: leitores e escritores coexistem; evita lock sob carga.
    # check_same_thread=False: o Flask atende requisições em threads distintas.
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
    except sqlite3.OperationalError:
        pass
    return conn


def init_db() -> None:
    conn = get_db()
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS contents (
            id           TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            type         TEXT NOT NULL,
            url          TEXT NOT NULL,
            logo         TEXT,
            category     TEXT,
            group_name   TEXT,
            description  TEXT,
            metadata     TEXT,
            series_name  TEXT,
            season       INTEGER,
            episode      INTEGER,
            created_at   TEXT,
            updated_at   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_contents_type     ON contents(type);
        CREATE INDEX IF NOT EXISTS idx_contents_category ON contents(category);
        CREATE INDEX IF NOT EXISTS idx_contents_name     ON contents(name);
        CREATE INDEX IF NOT EXISTS idx_contents_series   ON contents(series_name);

        CREATE TABLE IF NOT EXISTS categories (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  TEXT NOT NULL,
            type  TEXT NOT NULL,
            UNIQUE(name, type)
        );
        CREATE INDEX IF NOT EXISTS idx_categories_type ON categories(type);

        CREATE TABLE IF NOT EXISTS favorites (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id   TEXT NOT NULL,
            content_type TEXT NOT NULL,
            name         TEXT,
            logo         TEXT,
            url          TEXT,
            created_at   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_favorites_content ON favorites(content_id);

        CREATE TABLE IF NOT EXISTS watch_history (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id   TEXT NOT NULL,
            content_type TEXT NOT NULL,
            name         TEXT,
            logo         TEXT,
            position     REAL DEFAULT 0,
            duration     REAL DEFAULT 0,
            updated_at   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_history_content ON watch_history(content_id);

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------- #
# Leitura de conteúdos
# --------------------------------------------------------------------------- #

_SORT_COLUMNS = {
    "az": "name ASC",
    "za": "name DESC",
    "recent": "rowid DESC",
    "most": "updated_at DESC",
    "name": "name ASC",
}


def query_contents(
    typ: Optional[str] = None,
    category: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
    limit: int = 40,
    sort: str = "name",
):
    """Consulta paginada de conteúdos com filtros e ordenação.

    Retorna um dicionário com items, total, page, limit e pages.
    """
    conn = get_db()
    cur = conn.cursor()
    where = []
    params: list = []

    if typ:
        where.append("type = ?")
        params.append(typ)
    if category:
        where.append("category = ?")
        params.append(category)
    if q:
        # Busca em nome, categoria, grupo e (para séries) no nome da série.
        where.append(
            "(name LIKE ? OR category LIKE ? OR group_name LIKE ? OR series_name LIKE ?)"
        )
        like = f"%{q}%"
        params.extend([like, like, like, like])

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    cur.execute(f"SELECT COUNT(*) FROM contents{where_sql}", params)
    total = cur.fetchone()[0]

    order = _SORT_COLUMNS.get(sort, "name ASC")
    offset = max(0, (page - 1) * limit)
    cur.execute(
        f"SELECT * FROM contents{where_sql} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    items = [dict(r) for r in cur.fetchall()]
    conn.close()

    pages = (total + limit - 1) // limit if limit else 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages,
    }


def get_content(content_id: str) -> Optional[dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM contents WHERE id = ?", (content_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_metadata(content_id: str) -> Optional[dict]:
    """Lê e interpreta a coluna metadata (JSON) de um conteúdo."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT metadata FROM contents WHERE id = ?", (content_id,))
    row = cur.fetchone()
    conn.close()
    if not row or not row["metadata"]:
        return None
    try:
        return json.loads(row["metadata"])
    except (TypeError, ValueError):
        return None


def set_metadata(content_id: str, meta: dict) -> None:
    """Grava a coluna metadata (JSON) de um conteúdo."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE contents SET metadata = ?, updated_at = ? WHERE id = ?",
        (json.dumps(meta, ensure_ascii=False), _now(), content_id),
    )
    conn.commit()
    conn.close()


def get_series_episodes(series_name: str) -> list:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM contents WHERE type='series' AND series_name = ? "
        "ORDER BY season ASC, episode ASC",
        (series_name,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_categories(typ: Optional[str] = None) -> list:
    conn = get_db()
    cur = conn.cursor()
    if typ:
        cur.execute("SELECT name, type FROM categories WHERE type = ? ORDER BY name", (typ,))
    else:
        cur.execute("SELECT name, type FROM categories ORDER BY type, name")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def count_total() -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM contents")
    n = cur.fetchone()[0]
    conn.close()
    return n


def count_by_type(typ: str) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM contents WHERE type = ?", (typ,))
    n = cur.fetchone()[0]
    conn.close()
    return n


def get_series_list(limit: int = 60, offset: int = 0) -> list:
    """Lista de séries agrupadas (nome, nº de episódios, logo de capa)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT series_name, COUNT(*) AS eps, MAX(logo) AS logo "
        "FROM contents WHERE type='series' AND series_name IS NOT NULL "
        "GROUP BY series_name ORDER BY series_name LIMIT ? OFFSET ?",
        (limit, offset),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# --------------------------------------------------------------------------- #
# Favoritos
# --------------------------------------------------------------------------- #

def get_favorites() -> list:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM favorites ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def is_favorite(content_id: str) -> bool:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM favorites WHERE content_id = ?", (content_id,))
    ok = cur.fetchone() is not None
    conn.close()
    return ok


def add_favorite(data: dict) -> None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO favorites "
        "(content_id, content_type, name, logo, url, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            data.get("content_id"),
            data.get("content_type"),
            data.get("name"),
            data.get("logo"),
            data.get("url"),
            _now(),
        ),
    )
    conn.commit()
    conn.close()


def remove_favorite(content_id: str) -> None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM favorites WHERE content_id = ?", (content_id,))
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------- #
# Histórico de visualização ("Continuar assistindo")
# --------------------------------------------------------------------------- #

def get_history() -> list:
    conn = get_db()
    cur = conn.cursor()
    # Mantém apenas o registro mais recente por conteúdo.
    cur.execute(
        "SELECT * FROM watch_history ORDER BY updated_at DESC LIMIT 100"
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def add_history(data: dict) -> None:
    conn = get_db()
    cur = conn.cursor()
    cid = data.get("content_id")
    cur.execute(
        "SELECT id FROM watch_history WHERE content_id = ?", (cid,)
    )
    existing = cur.fetchone()
    if existing:
        cur.execute(
            "UPDATE watch_history SET name=?, logo=?, position=?, duration=?, "
            "updated_at=? WHERE content_id=?",
            (
                data.get("name"),
                data.get("logo"),
                data.get("position", 0),
                data.get("duration", 0),
                _now(),
                cid,
            ),
        )
    else:
        cur.execute(
            "INSERT INTO watch_history "
            "(content_id, content_type, name, logo, position, duration, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                cid,
                data.get("content_type"),
                data.get("name"),
                data.get("logo"),
                data.get("position", 0),
                data.get("duration", 0),
                _now(),
            ),
        )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------- #
# Settings (chave-valor)
# --------------------------------------------------------------------------- #

def set_setting(key: str, value) -> None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def get_setting(key: str, default=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return row["value"] if row else default


def get_recently_added(typ: str = None, limit: int = 20) -> list:
    """Conteúdos adicionados mais recentemente (ordem de ingestão = rowid).

    Desduplica por título: agrupa séries pela coluna series_name (cada série
    tem vários episódios com rowid distinto, mas todos compartilham o mesmo
    pôster), garantindo que o carrossel mostre títulos distintos.
    """
    conn = get_db()
    cur = conn.cursor()
    # rowid é coluna oculta do SQLite e não aparece em SELECT *;
    # expomos como ingest_order para poder ordenar na consulta externa.
    q = (
        "SELECT * FROM ("
        "  SELECT rowid AS ingest_order, *, ROW_NUMBER() OVER ("
        "    PARTITION BY COALESCE(series_name, name) ORDER BY rowid DESC"
        "  ) AS rn FROM contents"
    )
    params = []
    if typ:
        q += " WHERE type = ?"
        params.append(typ)
    q += ") WHERE rn = 1 ORDER BY ingest_order DESC LIMIT ?"
    params.append(limit)
    cur.execute(q, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_most_watched(typ: str = None, limit: int = 20) -> list:
    """Mais assistidos: conteúdos com maior número de registros no histórico.

    O histórico é atualizado a cada reprodução, então o total de linhas por
    content_id funciona como contador de visualizações. Desduplica por título
    para não repetir episódios da mesma série.
    """
    conn = get_db()
    cur = conn.cursor()
    q = (
        "SELECT c.*, COUNT(h.id) AS views FROM contents c "
        "JOIN watch_history h ON h.content_id = c.id"
    )
    params = []
    if typ:
        q += " WHERE c.type = ?"
        params.append(typ)
    q += (" GROUP BY COALESCE(c.series_name, c.name), c.id"
          " ORDER BY views DESC, h.updated_at DESC LIMIT ?")
    params.append(limit)
    cur.execute(q, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def clear_contents() -> None:
    """Remove todos os conteúdos (usado por "limpar cache")."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM contents")
    cur.execute("DELETE FROM categories")
    conn.commit()
    conn.close()
