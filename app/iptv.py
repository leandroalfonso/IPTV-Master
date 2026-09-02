"""Módulo de integração com a fonte IPTV.

Responsável por:
  - baixar/ler a lista (URL M3U, arquivo local ou Xtream Codes - modular);
  - interpretar os metadados (#EXTINF, tvg-*, group-title);
  - normalizar cada entrada em um objeto Content (live / movie / series);
  - detectar automaticamente o tipo quando possível;
  - persistir os resultados no SQLite.

A fonte NUNCA é exposta ao frontend: apenas o backend lê a URL do .env.
"""

import os
import re
import time
import hashlib
import logging
from urllib.parse import urlparse

import requests

from . import config
from .models import Content
from . import database

logger = logging.getLogger("streamvault.iptv")

# Timeout de rede (s) para baixar a lista.
_DOWNLOAD_TIMEOUT = 30

# Padrões usados para detectar tipo de conteúdo a partir de grupo/nome/url.
_MOVIE_HINTS = re.compile(r"\b(movie|filme|filmes|movies|cinema|hd)\b", re.I)
_SERIES_HINTS = re.compile(
    r"\b(series|serie|tv[ .-]?show|shows)\b", re.I
)
_SERIES_EPISODE_HINT = re.compile(
    r"(?P<name>.+?)[ ._-]+S(?P<season>\d{1,3})[ ._-]*(?:EP?)(?P<ep>\d{1,4})",
    re.I,
)
# Sufixo de temporada (com ou sem episódio), em qualquer posição do nome:
# "Nome S01", "Nome S01 E02", "Nome T1", "Nome Season 2", "Nome S01 Nome 10".
# Permite espaço opcional entre a palavra-chave e os dígitos (ex.: "SEASON 2").
_SERIES_SEASON_HINT = re.compile(
    r"(?:^|[\s._-])(?:S|SEASON|TEMP|T)[\s._-]*(\d{1,3})(?=[\s._-]|$)",
    re.I,
)
# Token de temporada "Sxx" solitário em qualquer posição (cobra "S05S03").
_SERIES_SEASON_TOKEN = re.compile(r"(?:^|[\s._-])S\d{1,3}", re.I)


def _clean_series_name(name: str) -> str:
    """Remove sufixos de temporada/episódio do nome da série.

    'MALHACAO S01' -> 'MALHACAO'; 'DARK MIRROR SEASON 2' -> 'DARK MIRROR';
    'YELLOWJACKETS S02 S020E9' -> 'YELLOWJACKETS'; 'THE GOOD DOCTOR S05S03'
    -> 'THE GOOD DOCTOR'. Assim temporadas distintas da mesma série são
    agrupadas em uma só capa.
    """
    # 1) Se casa o padrão SxxExx, usa o nome-base capturado.
    m = _SERIES_EPISODE_HINT.search(name)
    if m:
        name = m.group("name")
    # 2) Remove todos os tokens de temporada (Sxx / Season x / T1), em loop
    #    para pegar casos empilhados como "S05S03" e formas sem "E" (S0108).
    cleaned = name
    for _ in range(4):
        # Primeiro: casos sem separador "E" no fim (S0108 -> S01E08, S0405 -> S04E05).
        nxt = re.sub(r"\s+S(\d{2,4})$", "", cleaned, flags=re.I).strip()
        nxt = _SERIES_SEASON_HINT.sub(" ", nxt).strip()
        nxt = _SERIES_SEASON_TOKEN.sub(" ", nxt).strip()
        if nxt == cleaned:
            break
        cleaned = nxt
    cleaned = re.sub(r"^S\d{1,3}$", "", cleaned, flags=re.I).strip()
    return cleaned or name.strip()
_LIVE_HINTS = re.compile(
    r"\b(live|ao vivo|tv|canal|channel|canais|news|esporte|sport|brazil|usa|uk)\b",
    re.I,
)


def _stable_id(*parts) -> str:
    raw = "|".join(str(p) for p in parts if p)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _parse_extinf(line: str) -> dict:
    """Extrai atributos da linha #EXTINF:-1 ...Nome."""
    attrs = {}
    # Atributos no formato chave="valor"
    for m in re.finditer(r'(\w[\w-]*)="([^"]*)"', line):
        key, val = m.group(1).lower(), m.group(2)
        attrs[key] = val
    # Nome após a ÚLTIMA vírgula (o tvg-logo pode conter vírgulas internas).
    name = attrs.get("tvg-name") or ""
    if "," in line:
        # procura o último fechamento de atributo "...", antes do nome real
        last_comma = line.rfind(",")
        candidate = line[last_comma + 1:].strip()
        if candidate:
            name = candidate
    attrs["_name"] = name
    return attrs


def _classify_type(attrs: dict, url: str) -> tuple[str, str, int | None, int | None]:
    """Retorna (type, category, season, episode) deduzidos dos metadados."""
    group = attrs.get("group-title", "").strip()
    name = attrs.get("_name", "")
    url_l = url.lower()

    # 1) Séries com padrão SxxExx explícito.
    m = _SERIES_EPISODE_HINT.search(name)
    if m:
        series_name = m.group("name").strip()
        return (
            "series",
            group or "Séries",
            int(m.group("season")),
            int(m.group("ep")),
        )

    # 2) Pistas por grupo.
    if _SERIES_HINTS.search(group):
        return ("series", group, 1, None)
    if _MOVIE_HINTS.search(group):
        return ("movie", group, None, None)
    if _LIVE_HINTS.search(group):
        return ("live", group or "Canais", None, None)

    # 3) Pistas por nome.
    if _SERIES_HINTS.search(name):
        return ("series", group or "Séries", 1, None)
    if _MOVIE_HINTS.search(name):
        return ("movie", group or "Filmes", None, None)

    # 4) Pistas pela URL (extensões de VOD).
    if any(url_l.endswith(ext) for ext in (".mp4", ".mkv", ".avi", ".m4v", ".webm")):
        return ("movie", group or "Filmes", None, None)

    # 5) Default: ao vivo (caso mais comum em listas IPTV).
    return ("live", group or "Canais", None, None)


def parse_m3u(text: str) -> list[Content]:
    """Converte o texto de uma lista M3U em objetos Content normalizados."""
    now = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()

    items: list[Content] = []
    lines = text.splitlines()
    pending = None
    seen_ids = set()

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            pending = _parse_extinf(line)
        elif line.startswith("#"):
            # Comentários (#EXTGRP, #PLAYLIST, etc) - ignorados.
            continue
        elif pending is not None:
            # Linha de URL.
            url = line
            attrs = pending
            name = attrs.get("_name") or "Sem nome"
            group = attrs.get("group-title", "").strip()
            ttype, category, season, episode = _classify_type(attrs, url)

            cid = _stable_id(url, name, group)
            if cid in seen_ids:
                pending = None
                continue
            seen_ids.add(cid)

            # Nome da série sem o sufixo de temporada/episódio.
            _sm = _SERIES_EPISODE_HINT.search(name)
            if ttype == "series":
                if _sm:
                    series_name = _clean_series_name(_sm.group("name"))
                else:
                    series_name = _clean_series_name(name)
                    # Extrai o número da temporada de um sufixo "S01" solitário,
                    # para que S01/S02 da mesma série fiquem em temporadas distintas.
                    _ss = _SERIES_SEASON_HINT.search(name)
                    if _ss and not season:
                        season = int(_ss.group("season"))
            else:
                series_name = None
            content = Content(
                id=cid,
                name=name,
                type=ttype,
                url=url,
                logo=attrs.get("tvg-logo", ""),
                category=category or "Geral",
                group_name=group,
                description=attrs.get("tvg-name", ""),
                metadata="{}",
                series_name=series_name,
                season=season,
                episode=episode,
            )
            content._now = now  # type: ignore[attr-defined]
            items.append(content)
            pending = None

    return items


def _fetch_m3u_text() -> str:
    """Obtém o texto da lista de acordo com a configuração.

    Suporta URL http/https ou arquivo local (caminho relativo à BASE_DIR).
    """
    source = config.Config.IPTV_M3U_URL.strip()
    if not source:
        raise ValueError("IPTV_M3U_URL não configurada no .env")

    if source.startswith(("http://", "https://")):
        logger.info("Baixando lista IPTV de %s", source)
        resp = requests.get(source, timeout=_DOWNLOAD_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    else:
        # Arquivo local.
        path = source
        if not os.path.isabs(path):
            path = os.path.join(config.Config.BASE_DIR, source)
        logger.info("Lendo lista IPTV local: %s", path)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()


def load_from_m3u(force: bool = False) -> dict:
    """Baixa, parseia e persiste a lista M3U.

    Respeita o cache (IPTV_CACHE_MINUTES) salvo em settings, a menos que
    force=True. Retorna um resumo {channels, movies, series, total}.
    """
    if not force:
        last = database.get_setting("last_loaded_at")
        cache_min = config.Config.IPTV_CACHE_MINUTES
        if last:
            try:
                last_ts = float(last)
                if (time.time() - last_ts) < cache_min * 60:
                    # Cache válido: não baixa de novo.
                    return _summary()
            except (TypeError, ValueError):
                pass

    text = _fetch_m3u_text()
    items = parse_m3u(text)

    # Limpa e reinsere.
    database.clear_contents()
    conn = database.get_db()
    cur = conn.cursor()
    cats = set()
    for it in items:
        now = getattr(it, "_now", None)
        cur.execute(
            "INSERT OR REPLACE INTO contents "
            "(id, name, type, url, logo, category, group_name, description, "
            "metadata, series_name, season, episode, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            it.to_row(now or __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat()),
        )
        cats.add((it.category, it.type))
    for name, typ in cats:
        cur.execute(
            "INSERT OR IGNORE INTO categories(name, type) VALUES(?, ?)",
            (name, typ),
        )
    conn.commit()
    conn.close()

    database.set_setting("last_loaded_at", str(time.time()))
    database.set_setting("source_type", "m3u")
    return _summary()


def _summary() -> dict:
    return {
        "channels": database.count_by_type("live"),
        "movies": database.count_by_type("movie"),
        "series": database.count_by_type("series"),
        "total": database.count_total(),
    }


# --------------------------------------------------------------------------- #
# Xtream Codes (módulo opcional, preparado para uso futuro)
# --------------------------------------------------------------------------- #

def load_from_xtream() -> dict:
    """Placeholder para futura integração Xtream Codes.

    Quando IPTV_TYPE=xtream, aqui seriam feitas as chamadas à API
    (player_api.php) e os resultados normalizados para Content. Por ora
    levanta NotImplementedError para manter o contrato da função.
    """
    raise NotImplementedError(
        "Suporte a Xtream Codes será implementado como módulo separado."
    )


def refresh(force: bool = True) -> dict:
    """Atualiza a lista de acordo com o tipo de fonte configurado."""
    if config.Config.IPTV_TYPE == "xtream":
        return load_from_xtream()
    return load_from_m3u(force=force)


def is_configured() -> bool:
    if config.Config.IPTV_TYPE == "xtream":
        return bool(config.Config.IPTV_USERNAME and config.Config.IPTV_PASSWORD)
    return bool(config.Config.IPTV_M3U_URL.strip())
