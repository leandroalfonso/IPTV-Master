"""Rotas Flask: páginas HTML (Jinja) e API REST interna (JSON).

Todas as páginas herdam de base.html. A API é consumida via Fetch pelo
frontend (favoritos, pesquisa, histórico, atualização da lista).
"""

import threading
import logging

from flask import (
    Blueprint, render_template, request, jsonify, current_app, abort,
)

from . import database, iptv, config, tmdb

bp = Blueprint("main", __name__)
logger = logging.getLogger("streamvault.routes")

# Trava para evitar múltiplas atualizações simultâneas da lista.
_refresh_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _pagination_args():
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        limit = min(200, max(1, int(request.args.get("limit", 40))))
    except (TypeError, ValueError):
        limit = 40
    return page, limit


def _neighbor_ids(item, content_id):
    """Resolve IDs anterior/próximo para o player.

    Usa a lista mais coerente com o tipo de conteúdo atual:
    - live: todos os canais ao vivo
    - series: episódios da mesma série
    - movie: filmes da mesma categoria, com fallback para todos os filmes
    """
    current_id = str(content_id)
    ids = []

    if item["type"] == "live":
        items = database.query_contents(typ="live", limit=2000, page=1, sort="name")["items"]
        ids = [str(c["id"]) for c in items if c.get("id") is not None]
    elif item["type"] == "series" and item.get("series_name"):
        episodes = database.get_series_episodes(item["series_name"])
        ids = [str(ep["id"]) for ep in episodes if ep.get("id") is not None]
    elif item["type"] == "movie":
        movies = []
        if item.get("category"):
            movies = database.query_contents(
                typ="movie",
                category=item["category"],
                limit=2000,
                page=1,
                sort="name",
            )["items"]
        if not movies:
            movies = database.query_contents(typ="movie", limit=2000, page=1, sort="name")["items"]
        ids = [str(m["id"]) for m in movies if m.get("id") is not None]

    if current_id not in ids:
        return None, None

    i = ids.index(current_id)
    prev_id = ids[i - 1] if i > 0 else ids[-1]
    next_id = ids[i + 1] if i < len(ids) - 1 else ids[0]
    return prev_id, next_id


# --------------------------------------------------------------------------- #
# Carregamento inicial da lista
# --------------------------------------------------------------------------- #

def ensure_loaded() -> None:
    """Garante que a lista esteja no banco.

    Se não houver nada e houver URL configurada, dispara carregamento
    bloqueante uma única vez (na primeira requisição). Se o cache expirou,
    agenda atualização em background (sem travar o usuário).
    """
    if not iptv.is_configured():
        return
    if database.count_total() == 0:
        try:
            iptv.load_from_m3u(force=True)
        except Exception as exc:  # never crash boot on a bad list
            logger.warning("Falha ao carregar IPTV no boot: %s", exc)
        return
    # Verifica cache; se expirou, atualiza em background.
    last = database.get_setting("last_loaded_at")
    cache_min = config.Config.IPTV_CACHE_MINUTES
    import time
    if last:
        try:
            if (time.time() - float(last)) >= cache_min * 60:
                threading.Thread(target=_safe_refresh, daemon=True).start()
        except (TypeError, ValueError):
            pass


def _safe_refresh() -> None:
    if not _refresh_lock.acquire(blocking=False):
        return
    try:
        iptv.refresh(force=True)
    except Exception as exc:
        logger.warning("Atualização em background falhou: %s", exc)
    finally:
        _refresh_lock.release()


# --------------------------------------------------------------------------- #
# Páginas (HTML)
# --------------------------------------------------------------------------- #

@bp.route("/")
def index():
    history = database.get_history()
    # Hero: prioriza o conteúdo em andamento mais recente; senão um canal/filme.
    hero_item = history[0] if history else None
    if not hero_item:
        hero = database.query_contents(typ="live", limit=1)["items"]
        hero_item = hero[0] if hero else None
    if not hero_item:
        any_c = database.query_contents(limit=1)["items"]
        hero_item = any_c[0] if any_c else None

    resume = tmdb.hydrate(history[:12])
    favorites = tmdb.hydrate(database.get_favorites()[:12])
    live = database.query_contents(typ="live", limit=20)["items"]
    movies = tmdb.hydrate(database.query_contents(typ="movie", limit=20)["items"])
    series = database.get_series_list(limit=20)
    most_watched = tmdb.hydrate(database.get_most_watched(limit=20))
    recently_added = tmdb.hydrate(database.get_recently_added(limit=20))
    categories = database.get_categories()[:18]

    return render_template(
        "index.html",
        hero=hero_item,
        resume=resume,
        favorites=favorites,
        live=live,
        movies=movies,
        series=series,
        most_watched=most_watched,
        recently_added=recently_added,
        categories=categories,
        configured=iptv.is_configured(),
        total=database.count_total(),
    )


@bp.route("/canais")
def canais():
    categories = database.get_categories("live")
    items = database.query_contents(typ="live", limit=24, page=1)["items"]
    return render_template(
        "canais.html", categories=categories, items=items,
        configured=iptv.is_configured(),
    )


@bp.route("/filmes")
def filmes():
    categories = database.get_categories("movie")
    rows = database.query_contents(typ="movie", limit=24, page=1)
    items = tmdb.hydrate(rows["items"])
    return render_template(
        "filmes.html", categories=categories, items=items,
        configured=iptv.is_configured(),
    )


@bp.route("/series")
def series():
    series_list = database.get_series_list(limit=24, offset=0)
    categories = database.get_categories("series")
    return render_template(
        "series.html", series_list=series_list, categories=categories,
        configured=iptv.is_configured(),
    )


@bp.route("/minha-lista")
def minha_lista():
    favorites = database.get_favorites()
    return render_template(
        "minha_lista.html", favorites=favorites,
        configured=iptv.is_configured(),
    )


@bp.route("/configuracoes")
def configuracoes():
    summary = {
        "channels": database.count_by_type("live"),
        "movies": database.count_by_type("movie"),
        "series": database.count_by_type("series"),
        "total": database.count_total(),
    }
    last = database.get_setting("last_loaded_at")
    return render_template(
        "configuracoes.html",
        summary=summary,
        last_loaded=last,
        cache_minutes=config.Config.IPTV_CACHE_MINUTES,
        iptv_type=config.Config.IPTV_TYPE,
        configured=iptv.is_configured(),
        # Nunca expõe a URL/senha real ao template.
    )


@bp.route("/assistir/<content_id>")
def assistir(content_id):
    item = database.get_content(content_id)
    if not item:
        abort(404)
    history = next(
        (h for h in database.get_history() if h["content_id"] == content_id), None
    )
    start = history["position"] if history else 0

    # Navegação anterior/próximo no player.
    prev_id, next_id = _neighbor_ids(item, content_id)

    return render_template(
        "assistir.html", item=item, start=start,
        prev_id=prev_id, next_id=next_id,
        configured=iptv.is_configured(),
    )


@bp.route("/detalhes-series/<path:series_name>")
def detalhes_series(series_name):
    episodes = database.get_series_episodes(series_name)
    if not episodes:
        abort(404)
    # Agrupa por temporada.
    seasons = {}
    cover = None
    for ep in episodes:
        s = ep.get("season") or 1
        seasons.setdefault(s, []).append(ep)
        if not cover and ep.get("logo"):
            cover = ep["logo"]
    return render_template(
        "detalhes_series.html",
        series_name=series_name,
        episodes=episodes,
        seasons=seasons,
        cover=cover,
        configured=iptv.is_configured(),
    )


@bp.route("/detalhes/<content_id>")
def detalhes(content_id):
    item = database.get_content(content_id)
    if not item:
        abort(404)
    episodes = []
    if item["type"] == "series" and item.get("series_name"):
        episodes = database.get_series_episodes(item["series_name"])
    is_fav = database.is_favorite(content_id)
    # Enriquecimento TMDB (somente filmes): busca sinopse/nota/ano/gêneros.
    tmdb_meta = tmdb.get_tmdb(item) if item["type"] == "movie" else None
    return render_template(
        "detalhes.html", item=item, episodes=episodes, is_fav=is_fav,
        tmdb_meta=tmdb_meta, configured=iptv.is_configured(),
    )


# --------------------------------------------------------------------------- #
# API REST
# --------------------------------------------------------------------------- #

@bp.route("/api/status")
def api_status():
    return jsonify({
        "configured": iptv.is_configured(),
        "total": database.count_total(),
        "channels": database.count_by_type("live"),
        "movies": database.count_by_type("movie"),
        "series": database.count_by_type("series"),
        "last_loaded_at": database.get_setting("last_loaded_at"),
    })


@bp.route("/api/local-ip")
def api_local_ip():
    """IP local da máquina na rede — usado pelo Google Cast para montar a URL
    absoluta do stream que a TV/Chromecast vai buscar (a página pode estar
    sendo vista via localhost, mas a TV precisa de um IP acessível na LAN)."""
    import socket
    ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Conecta a um endereço público sem enviar dados; retorna a
            # interface de rede usada para alcançá-lo.
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        pass
    return jsonify({"ip": ip})


@bp.route("/api/contents")
def api_contents():
    page, limit = _pagination_args()
    typ = request.args.get("type")
    category = request.args.get("category")
    q = request.args.get("q")
    sort = request.args.get("sort", "name")
    res = database.query_contents(
        typ=typ, category=category, q=q, page=page, limit=limit, sort=sort
    )
    return jsonify(res)


@bp.route("/api/live")
def api_live():
    page, limit = _pagination_args()
    category = request.args.get("category")
    q = request.args.get("q")
    res = database.query_contents(
        typ="live", category=category, q=q, page=page, limit=limit
    )
    return jsonify(res)


@bp.route("/api/movies")
def api_movies():
    page, limit = _pagination_args()
    category = request.args.get("category")
    q = request.args.get("q")
    res = database.query_contents(
        typ="movie", category=category, q=q, page=page, limit=limit
    )
    return jsonify(res)


@bp.route("/api/series")
def api_series():
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    limit = min(200, max(1, int(request.args.get("limit", 60))))
    return jsonify(database.get_series_list(limit=limit, offset=(page - 1) * limit))


@bp.route("/api/categories")
def api_categories():
    typ = request.args.get("type")
    return jsonify(database.get_categories(typ))


@bp.route("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 1:
        return jsonify({"channels": [], "movies": [], "series": []})
    ch = database.query_contents(typ="live", q=q, limit=12)["items"]
    mv = database.query_contents(typ="movie", q=q, limit=12)["items"]
    # Séries agrupadas.
    all_series = database.get_series_list(limit=300)
    sr = [s for s in all_series if q.lower() in s["series_name"].lower()]
    # Também inclui episódios que casam.
    ep = database.query_contents(typ="series", q=q, limit=12)["items"]
    return jsonify({
        "channels": ch,
        "movies": mv,
        "series": sr[:12],
        "series_episodes": ep,
    })


@bp.route("/api/favorites", methods=["GET"])
def api_favorites_get():
    return jsonify(database.get_favorites())


@bp.route("/api/favorites", methods=["POST"])
def api_favorites_post():
    data = request.get_json(silent=True) or {}
    cid = data.get("content_id")
    if not cid:
        return jsonify({"error": "content_id obrigatório"}), 400
    database.add_favorite({
        "content_id": cid,
        "content_type": data.get("content_type", ""),
        "name": data.get("name", ""),
        "logo": data.get("logo", ""),
        "url": data.get("url", ""),
    })
    return jsonify({"ok": True, "favorite": True})


@bp.route("/api/favorites/<content_id>", methods=["DELETE"])
def api_favorites_delete(content_id):
    database.remove_favorite(content_id)
    return jsonify({"ok": True, "favorite": False})


@bp.route("/api/history", methods=["GET"])
def api_history_get():
    return jsonify(database.get_history())


@bp.route("/api/history", methods=["POST"])
def api_history_post():
    data = request.get_json(silent=True) or {}
    cid = data.get("content_id")
    if not cid:
        return jsonify({"error": "content_id obrigatório"}), 400
    database.add_history({
        "content_id": cid,
        "content_type": data.get("content_type", ""),
        "name": data.get("name", ""),
        "logo": data.get("logo", ""),
        "position": float(data.get("position", 0) or 0),
        "duration": float(data.get("duration", 0) or 0),
    })
    return jsonify({"ok": True})


@bp.route("/api/iptv/refresh", methods=["POST"])
def api_refresh():
    if not _refresh_lock.acquire(blocking=False):
        return jsonify({"busy": True, "message": "Atualização já em andamento."}), 409
    try:
        summary = iptv.refresh(force=True)
        return jsonify({"ok": True, **summary})
    except Exception as exc:
        logger.error("Erro ao atualizar lista: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        _refresh_lock.release()


@bp.route("/api/iptv/clear", methods=["POST"])
def api_clear():
    try:
        database.clear_contents()
        database.set_setting("last_loaded_at", "")
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.route("/api/config", methods=["POST"])
def api_config_post():
    """Atualiza configurações do .env via página de Configurações."""
    data = request.get_json(silent=True) or {}
    allowed = {"IPTV_M3U_URL", "IPTV_TYPE", "IPTV_CACHE_MINUTES"}
    updates = {}
    for k, v in data.items():
        if k in allowed:
            updates[k] = v
    if not updates:
        return jsonify({"error": "Nada para atualizar"}), 400
    config.save_env(updates)
    return jsonify({"ok": True, "updates": list(updates.keys())})
