"""Integração com The Movie Database (TMDB).

Enriquece filmes com dados relevantes (sinopse, nota, ano, gêneros, duração,
backdrop) que a lista IPTV não traz. Os dados são buscados uma vez e guardados
na coluna `metadata` da linha do filme no banco — chamadas de rede acontecem
apenas quando o usuário abre a página de detalhes de um filme que ainda não tem
dados do TMDB (ou quando se pede refresh explícito).
"""

import json
import logging
import time

import requests

from . import config, database

logger = logging.getLogger("streamvault.tmdb")

API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p"

# Cache em memória por content_id: evita refazer parse/leitura do banco a cada
# renderização da mesma página.
_cache: dict[str, dict] = {}
CACHE_TTL = 86400  # 24h


def is_enabled() -> bool:
    return bool(config.Config.TMDB_API_KEY)


def _get(path: str, params: dict) -> dict:
    params = dict(params)
    params["api_key"] = config.Config.TMDB_API_KEY
    params["language"] = config.Config.TMDB_LANGUAGE
    r = requests.get(API + path, params=params, timeout=8)
    r.raise_for_status()
    return r.json()


def _clean_title(title: str) -> str:
    """Remove ruídos comuns de nomes em listas IPTV para o TMDB conseguir
    casar: prefixos entre colchetes/parênteses ("[24H]", "(DUB)", "[FULL]"),
    sufixos de qualidade e marcadores de idioma."""
    import re

    clean = (title or "").strip()
    # prefixos tipo [24H], (DUB), [LEG], {4K}
    clean = re.sub(r"^[\[\(\{][^\]\)\}]*[\]\)\}]\s*", "", clean)
    # sufixos repetidos de qualidade/idioma no fim: "HD+", "4K LEG", "(DUB)"
    pat = (r"(?:[\s\-\|]+(?:HD\+?|FHD|UHD|4K|FULL\s*HD|BLURAY|BLU-?RAY|REMUX|SD|HD|"
           r"DUB(LADO)?|LEG(ENDADO)?|NAC|PT-?BR|EN|ESP)(?![-\w])"
           r"|[\s\-\|]*[\[\(\{](?:DUB(LADO)?|LEG(ENDADO)?|NAC|FULL\s*HD|HD|4K|FULL)[\]\)\}])\s*$")
    prev = None
    while prev != clean:
        prev = clean
        clean = re.sub(pat, "", clean, flags=re.IGNORECASE).strip()
    return clean


def _search_movie(title: str) -> dict | None:
    data = _get("/search/movie", {"query": title, "include_adult": False})
    results = data.get("results") or []
    if not results:
        return None
    # O primeiro resultado costuma ser o mais relevante; se houver um match
    # exato (case-insensitive) de título, prefere-o.
    low = title.lower()
    for r in results:
        if (r.get("title") or "").lower() == low:
            return r
    return results[0]


def _fetch_tmdb(content: dict) -> dict | None:
    """Busca os dados do TMDB para um item (content) do tipo movie."""
    found = _search_movie(_clean_title(content.get("name", "")))
    if not found:
        return None
    det = _get(f"/movie/{found['id']}", {})
    backdrop = ""
    if det.get("backdrop_path"):
        backdrop = f"{IMG}/w1280{det['backdrop_path']}"
    poster = ""
    if det.get("poster_path"):
        poster = f"{IMG}/w500{det['poster_path']}"
    return {
        "tmdb_id": found["id"],
        "overview": det.get("overview") or "",
        "tagline": det.get("tagline") or "",
        "rating": round(float(det.get("vote_average") or 0), 1),
        "vote_count": det.get("vote_count") or 0,
        "year": (det.get("release_date") or "")[:4],
        "runtime": det.get("runtime") or 0,
        "genres": [g["name"] for g in (det.get("genres") or [])],
        "backdrop": backdrop,
        "poster": poster,
        "original_title": det.get("original_title") or "",
        "_fetched": time.time(),
    }


def get_tmdb(content: dict, force: bool = False) -> dict | None:
    """Retorna os metadados TMDB de um item de conteúdo.

    - Se já houver dados no cache em memória ou na coluna metadata do banco,
      usa-os (sem chamada de rede).
    - Senão busca no TMDB (apenas para filmes) e grava no banco.
    - Retorna None se o recurso estiver desligado, o item não for filme, ou a
      busca falhar/não encontrar.
    """
    if not is_enabled():
        return None
    cid = content.get("id")
    if not cid:
        return None

    # 1) cache em memória (quente)
    cached = _cache.get(cid)
    if cached and not force and (time.time() - cached.get("_fetched", 0)) < CACHE_TTL:
        return cached

    # 2) metadata já gravado no banco
    meta = database.get_metadata(cid)
    if meta and meta.get("tmdb") and not force:
        tmdb = dict(meta["tmdb"])
        tmdb["_fetched"] = meta.get("_ts") or time.time()
        _cache[cid] = tmdb
        return tmdb

    # 3) busca na API (somente filmes)
    if content.get("type") != "movie":
        return None
    try:
        tmdb = _fetch_tmdb(content)
    except Exception as exc:
        logger.warning("TMDB falhou para %r: %s", content.get("name"), exc)
        return None
    if not tmdb:
        return None

    database.set_metadata(cid, {"tmdb": tmdb, "_ts": tmdb["_fetched"]})
    _cache[cid] = tmdb
    return tmdb


def hydrate(items: list[dict]) -> list[dict]:
    """Preenche campos year/rating/duration/description dos cards a partir do
    metadata TMDB já gravado no banco (sem chamada de rede — só leitura).

    Usado nas listas (início, filmes) para popular os campos que o card já
    espera exibir. A chamada à API fica sob demanda na página de detalhes.
    """
    out = []
    for it in items:
        d = dict(it)
        meta = database.get_metadata(d.get("id", ""))
        tm = (meta or {}).get("tmdb")
        if tm:
            d["year"] = tm.get("year") or d.get("year")
            d["rating"] = tm.get("rating") or d.get("rating")
            mins = tm.get("runtime") or 0
            if mins:
                d["duration"] = f"{mins // 60}h{mins % 60:02d}"
            d["description"] = tm.get("overview") or d.get("description") or ""
            # Pôster TMDB quando o logo da lista IPTV não existe (a maioria dos
            # filmes VOD não traz imagem) — card ganha arte real.
            if tm.get("poster") and not d.get("logo"):
                d["logo"] = tm["poster"]
            d["genres"] = tm.get("genres") or d.get("genres") or []
        out.append(d)
    return out


def enrich_pending(batch: int = 200, delay: float = 0.12, max_rounds: int = 0) -> int:
    """Enriquece filmes ainda sem metadata TMDB, em lotes (para rodar em
    background no boot, sem travar requests).

    - Busca apenas linhas type='movie' com metadata vazio/'{}'.
    - Sem match na API, grava {"tmdb_try": ts} para não re-tentar a cada rodada.
    - delay entre filmes mantém ~6 req/s (limite TMDB é 50/s).
    Retorna o total enriquecido (para logs/testes).
    """
    import sqlite3

    total = 0
    rounds = 0
    while True:
        conn = database.get_db()
        try:
            rows = conn.execute(
                "SELECT id, name, type FROM contents "
                "WHERE type='movie' AND (metadata IS NULL OR metadata='{}') "
                "ORDER BY rowid LIMIT ?",
                (batch,),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return total
        for cid, name, typ in rows:
            item = {"id": cid, "name": name, "type": typ}
            try:
                found = _fetch_tmdb(item)
            except Exception as exc:
                logger.warning("TMDB enrich falhou para %r: %s", name, exc)
                found = None
            if found:
                database.set_metadata(cid, {"tmdb": found, "_ts": found["_fetched"]})
                total += 1
            else:
                database.set_metadata(cid, {"tmdb_try": time.time()})
            time.sleep(delay)
        rounds += 1
        if max_rounds and rounds >= max_rounds:
            return total


def start_enrich_worker() -> None:
    """Dispara o enriquecimento em thread daemon (chamado no boot do app)."""
    import threading

    if not is_enabled():
        return
    conn = database.get_db()
    try:
        pending = conn.execute(
            "SELECT COUNT(*) FROM contents "
            "WHERE type='movie' AND (metadata IS NULL OR metadata='{}')"
        ).fetchone()[0]
    finally:
        conn.close()
    if not pending:
        return

    def _run():
        try:
            n = enrich_pending()
            logger.info("TMDB enrich worker: %d filmes enriquecidos", n)
        except Exception as exc:
            logger.warning("TMDB enrich worker abortou: %s", exc)

    t = threading.Thread(target=_run, name="tmdb-enrich", daemon=True)
    t.start()
