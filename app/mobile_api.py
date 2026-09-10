"""API REST para clientes nativos (app React Native).

O app nunca fala com o banco: fala apenas com estas rotas JSON sobre HTTPS.
Autenticação por token de longa duração (HMAC stateless, mesmo esquema do
handoff admin), sem cookies — cookie/session não funciona bem em clients RN.

Formato do token:  base64url(payload_json).base64url(hmac_sha256)
Payload: {"uid": <usuário>, "exp": <unix>, "scope": "app"}

Credenciais: usuário em APP_USERNAME (padrão "leandro") e hash PBKDF2 em
APP_PASSWORD_HASH. Configure com:
  python -m app.mobile_api --set-senha <senha> [--usuario nome]
que grava o hash no .env (nunca a senha em texto claro).
"""

from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import json
import os
import time

import flask
from flask import Blueprint, current_app, jsonify, redirect, request

from . import config, database, tmdb

bp = Blueprint("mobile_api", __name__)

TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 dias — app não fica pedindo login
DEFAULT_USERNAME = "leandro"
PBKDF2_ITERATIONS = 200_000


# --------------------------------------------------------------------------- #
# Senha (hash PBKDF2 em .env, nunca texto claro)
# --------------------------------------------------------------------------- #

def _username() -> str:
    return os.getenv("APP_USERNAME", DEFAULT_USERNAME)


def _salt() -> bytes:
    """Salt derivado do segredo + usuário: muda se o segredo mudar."""
    return hashlib.sha256(
        f"{current_app.config.get('IPTV_AUTH_SECRET', '')}|{_username()}".encode()
    ).digest()


def _derive(password: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), _salt(), PBKDF2_ITERATIONS
    ).hex()


def _stored_hash() -> str:
    return os.getenv("APP_PASSWORD_HASH", "")


def _password_ok(password: str) -> bool:
    stored = _stored_hash()
    return bool(stored) and hmac.compare_digest(_derive(password), stored)


# --------------------------------------------------------------------------- #
# Token stateless (mesma construção de app/auth.py, com expiração própria)
# --------------------------------------------------------------------------- #

def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(encoded_payload: str) -> str:
    secret = current_app.config.get("IPTV_AUTH_SECRET", "")
    return _b64e(hmac.new(secret.encode(), encoded_payload.encode(),
                          hashlib.sha256).digest())


def issue_token(username: str) -> tuple[str, float]:
    exp = time.time() + TOKEN_TTL_SECONDS
    payload = {"uid": username, "exp": exp, "scope": "app"}
    encoded = _b64e(json.dumps(payload).encode())
    return f"{encoded}.{_sign(encoded)}", exp


def verify_token(token: str) -> dict | None:
    if not token or "." not in token:
        return None
    encoded, supplied = token.split(".", 1)
    if not current_app.config.get("IPTV_AUTH_SECRET", ""):
        return None
    if not hmac.compare_digest(supplied, _sign(encoded)):
        return None
    try:
        payload = json.loads(_b64d(encoded))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    if payload.get("scope") != "app":
        return None
    if float(payload.get("exp", 0)) < time.time():
        return None
    return payload


def app_api(fn):
    """Exige Authorization: Bearer <token> OU sessão de navegador.

    Mantém o site existente intacto (cookie/session) enquanto o app nativo
    usa Bearer. Qualquer um dos dois vale acesso.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from . import auth
        header = request.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        payload = verify_token(token)
        if payload:
            request.app_user = payload.get("uid")
            return fn(*args, **kwargs)
        if auth.is_authenticated():
            request.app_user = "web"
            return fn(*args, **kwargs)
        return jsonify({
            "error": "unauthorized",
            "message": "Token ausente/expirado. Use POST /api/app/login.",
        }), 401
    return wrapper


# --------------------------------------------------------------------------- #
# Helpers de payload
# --------------------------------------------------------------------------- #

_EXTRA = ("year", "rating", "certification", "duration", "genres")


def _card(item: dict, stream: bool = False) -> dict:
    out = {
        "id": item.get("id"),
        "name": item.get("name"),
        "type": item.get("type"),
        "logo": item.get("logo") or "",
        "category": item.get("category") or "",
        "description": item.get("description") or "",
    }
    for k in _EXTRA:
        if item.get(k) not in (None, ""):
            out[k] = item[k]
    if stream:
        out["stream"] = _stream_url(item)
    return out


def _stream_url(item: dict) -> str:
    """URL do canal/filme: direta para o app nativo (sem CORS, sem proxy)."""
    return item.get("url") or ""


def _hydrate(items: list[dict]) -> list[dict]:
    """Filtra canais disfarçados (resíduos antigos type='movie')."""
    import re
    hd = re.compile(r"\bhd\s*\+?\b|\b4k\b|uhd", re.I)
    keep = []
    for it in items:
        if it.get("type") == "movie" and hd.search(it.get("name") or "") \
                and not (database.get_metadata(it["id"]) or {}).get("tmdb"):
            continue
        keep.append(it)
    return keep


# --------------------------------------------------------------------------- #
# Rotas
# --------------------------------------------------------------------------- #

@bp.route("/api/app/login", methods=["POST"])
def app_login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or _username()).strip().lower()
    password = data.get("password") or ""
    if username != _username().lower() or not password:
        return jsonify({"error": "credenciais_invalidas"}), 401
    if not _password_ok(password):
        # small delay-ish: PBKDF2 já custa ~100ms, suficiente contra brute force
        return jsonify({"error": "credenciais_invalidas"}), 401
    token, exp = issue_token(username)
    return jsonify({
        "token": token,
        "expires_at": exp,
        "username": username,
        "ttl_days": TOKEN_TTL_SECONDS // 86400,
    })


@bp.route("/api/app/home")
@app_api
def app_home():
    live = database.query_contents(typ="live", limit=12)["items"]
    return jsonify({
        "status": {
            "total": database.count_total(),
            "movies": database.count_by_type("movie"),
            "channels": database.count_by_type("live"),
            "series": database.count_by_type("series"),
        },
        "continue_watching": [_card(h) for h in database.get_history()[:10]],
        "top_rated": [_card(m) for m in
                      tmdb.hydrate(database.get_top_rated("movie", 10))],
        "recent": [_card(m) for m in
                   tmdb.hydrate(database.get_recently_added("movie", 10))],
        "live": [_card(c) for c in live],
        "series": database.get_series_list(limit=12),
    })


@bp.route("/api/app/movies")
@app_api
def app_movies():
    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(60, max(1, int(request.args.get("limit", 24))))
    except ValueError:
        return jsonify({"error": "page/limit invalidos"}), 400
    res = database.query_contents(
        typ="movie", category=request.args.get("category") or None,
        q=request.args.get("q") or None, page=page, limit=limit,
        sort=request.args.get("sort", "name"),
    )
    items = _hydrate(tmdb.hydrate(res["items"]))
    res["items"] = [_card(m) for m in items]
    return jsonify(res)


@bp.route("/api/app/channels")
@app_api
def app_channels():
    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(200, max(1, int(request.args.get("limit", 60))))
    except ValueError:
        return jsonify({"error": "page/limit invalidos"}), 400
    res = database.query_contents(
        typ="live", category=request.args.get("category") or None,
        q=request.args.get("q") or None, page=page, limit=limit,
    )
    res["items"] = [_card(c) for c in res["items"]]
    return jsonify(res)


@bp.route("/api/app/series")
@app_api
def app_series():
    try:
        limit = min(200, max(1, int(request.args.get("limit", 60))))
    except ValueError:
        return jsonify({"error": "limit invalido"}), 400
    return jsonify(database.get_series_list(limit=limit))


@bp.route("/api/app/detalhes/<content_id>")
@app_api
def app_detalhes(content_id):
    item = database.get_content(content_id)
    if not item:
        return jsonify({"error": "not_found"}), 404
    meta = tmdb.get_tmdb(item) if item.get("type") == "movie" else None
    tm = (meta or {}).get("tmdb") or {}
    card = _card(item, stream=True)
    if tm:
        card["rating"] = tm.get("rating") or card.get("rating")
        card["certification"] = tm.get("certification") or card.get("certification")
    return jsonify({
        "item": card,
        "tmdb": tm or None,
        "variants": [_card(v) for v in database.get_movie_variants(content_id)],
        "favorite": database.is_favorite(content_id),
    })


@bp.route("/api/app/series/<path:series_name>")
@app_api
def app_series_episodios(series_name):
    eps = database.get_series_episodes(series_name)
    if not eps:
        return jsonify({"error": "not_found"}), 404
    seasons: dict[str, list] = {}
    for e in eps:
        seasons.setdefault(str(e.get("season") or 1), []).append(
            _card(e, stream=True))
    return jsonify({"series_name": series_name, "seasons": seasons,
                    "total": len(eps)})


@bp.route("/api/app/play/<content_id>")
@app_api
def app_play(content_id):
    """Resolve a URL real do stream para o player nativo (sem CORS em RN)."""
    item = database.get_content(content_id)
    if not item:
        return jsonify({"error": "not_found"}), 404
    return jsonify({
        "id": content_id,
        "name": item.get("name"),
        "type": item.get("type"),
        "url": _stream_url(item),
        "poster": item.get("logo") or "",
    })


@bp.route("/api/app/categories")
@app_api
def app_categories():
    return jsonify(database.get_categories(request.args.get("type") or None))


@bp.route("/api/app/search")
@app_api
def app_search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 1:
        return jsonify({"channels": [], "movies": [], "series": []})
    ch = database.query_contents(typ="live", q=q, limit=15)["items"]
    mv = _hydrate(tmdb.hydrate(
        database.query_contents(typ="movie", q=q, limit=15)["items"]))
    eps = database.query_contents(typ="series", q=q, limit=15)["items"]
    all_series = database.get_series_list(limit=300)
    sr = [s for s in all_series if q.lower() in s["series_name"].lower()][:15]
    return jsonify({
        "channels": [_card(c) for c in ch],
        "movies": [_card(m) for m in mv],
        "series": sr,
        "series_episodes": [_card(e) for e in eps],
    })


@bp.route("/api/app/favorites")
@app_api
def app_favorites():
    return jsonify(database.get_favorites())


@bp.route("/api/app/favorites", methods=["POST"])
@app_api
def app_favorite_add():
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


@bp.route("/api/app/favorites/<content_id>", methods=["DELETE"])
@app_api
def app_favorite_del(content_id):
    database.remove_favorite(content_id)
    return jsonify({"ok": True, "favorite": False})


@bp.route("/api/app/history")
@app_api
def app_history():
    return jsonify(database.get_history())


@bp.route("/api/app/history", methods=["POST"])
@app_api
def app_history_add():
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


@bp.route("/api/app/tts")
@app_api
def app_tts():
    """Redireciona para a rota /tts existente (mesmo áudio/voz/cache)."""
    from urllib.parse import urlencode
    return redirect("/tts?" + urlencode(request.args.to_dict()))


# --------------------------------------------------------------------------- #
# CLI: python -m app.mobile_api --set-senha <senha> [--usuario nome]
# --------------------------------------------------------------------------- #

def _cli() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        prog="mobile_api",
        description="Configura credenciais do app (hash PBKDF2 no .env).")
    parser.add_argument("--set-senha", metavar="SENHA",
                        help="Gera e grava APP_PASSWORD_HASH no .env")
    parser.add_argument("--usuario", metavar="NOME", default=None,
                        help="APP_USERNAME no .env")
    ns = parser.parse_args()
    if not (ns.set_senha or ns.usuario):
        parser.print_help()
        return

    holder = {}
    if ns.usuario:
        os.environ["APP_USERNAME"] = ns.usuario
    if ns.set_senha:
        probe = flask.Flask("cli")
        probe.config["IPTV_AUTH_SECRET"] = config.Config.IPTV_AUTH_SECRET
        with probe.app_context():
            holder["hash"] = _derive(ns.set_senha)

    updates = {}
    if ns.usuario:
        updates["APP_USERNAME"] = ns.usuario
    if "hash" in holder:
        updates["APP_PASSWORD_HASH"] = holder["hash"]
    config.save_env(updates)

    if "hash" in holder:
        probe = flask.Flask("cli")
        probe.config["IPTV_AUTH_SECRET"] = config.Config.IPTV_AUTH_SECRET
        with probe.app_context():
            ok = _password_ok(ns.set_senha)
        print(f"APP_PASSWORD_HASH gravado no .env; autovalidacao: {ok}")
    if ns.usuario:
        print(f"APP_USERNAME gravado: {ns.usuario}")


if __name__ == "__main__":
    _cli()
