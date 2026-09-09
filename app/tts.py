"""Text-to-speech (voz) para descrições — Microsoft Edge TTS via edge-tts.

Contexto técnico:
  - A API do Edge TTS (speech.platform.bing.com) exige o header ``Sec-MS-GEC``,
    um token derivado do relógio com janela de 5 minutos (SHA256 do timestamp
    Windows arredondado + trusted client token). Browsers não conseguem abri
    o WebSocket com esse header -> a síntese precisa ser feita server-side.
  - O ``edge-tts`` já cuida do token, do ajuste de clock skew (header ``Date``
    da resposta em caso de 403) e do streaming de áudio MP24/RAW.

Arquitetura:
  - Flask é síncrono; edge-tts é asyncio. A ponte: uma thread roda um event
    loop próprio consumindo o stream e empurrando chunks em um Queue; o
    generator do Flask lê o queue e faz streaming response (progressive
    MP3 que o <audio> do browser toca enquanto baixa).
  - Cache em memória (chave = hash(voz+texto), TTL 6h): descrições são
    estáticas, então cada filme sintetiza uma única vez por processo.
  - Se a Microsoft estiver fora/limite, a rota responde 502 e o frontend
    degrada para a Web Speech API local do dispositivo.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import queue
import threading
import time

from flask import Blueprint, Response, jsonify, request

from . import database, tmdb

logger = logging.getLogger("streamvault.tts")

bp = Blueprint("tts", __name__)

CACHE_TTL = 6 * 3600
CACHE_MAX_ITEMS = 200
MAX_CHARS = 2400  # limite defensivo do tamanho da fala

# Vozes padrão pt-BR (Microsoft). Se a lista mudar, cai no fallback do browser.
VOICE_BY_LANG = {
    "pt": "pt-BR-AntonioNeural",
    "pt-br": "pt-BR-AntonioNeural",
    "en": "en-US-GuyNeural",
    "es": "es-ES-AlvaroNeural",
    "fr": "fr-FR-DenisNeural",
    "de": "de-DE-ConradNeural",
    "it": "it-IT-DiegoNeural",
}

# --------------------------------------------------------------------------- #
# Cache de áudio sintetizado
# --------------------------------------------------------------------------- #
_cache: dict[str, tuple[float, bytes]] = {}


def _cache_key(voice: str, text: str) -> str:
    return hashlib.sha256(f"{voice}|{text}".encode()).hexdigest()[:32]


def _cache_get(key: str) -> bytes | None:
    item = _cache.get(key)
    if not item:
        return None
    ts, data = item
    if time.time() - ts > CACHE_TTL:
        _cache.pop(key, None)
        return None
    return data


def _cache_put(key: str, data: bytes) -> None:
    if len(_cache) >= CACHE_MAX_ITEMS:
        # remove o mais antigo
        oldest = min(_cache.items(), key=lambda kv: kv[1][0])[0]
        _cache.pop(oldest, None)
    _cache[key] = (time.time(), data)


# --------------------------------------------------------------------------- #
# Ponte async -> sync (thread própria com event loop)
# --------------------------------------------------------------------------- #
_SENTINEL = object()


def _run_synth(voice: str, text: str, out: queue.Queue) -> None:
    async def _stream():
        from edge_tts import Communicate

        com = Communicate(text, voice)
        async for chunk in com.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                out.put(chunk["data"])

    try:
        asyncio.run(_stream())
    except Exception as exc:  # noqa: BLE001
        logger.warning("edge-tts falhou (voz=%s): %s", voice, exc)
        out.put(exc)
    finally:
        out.put(_SENTINEL)


def _synthesize(voice: str, text: str):
    """Gera chunks de MP3. Se o primeiro chunk falhar, propaga a exceção
    (chamador ainda não enviou headers -> pode responder 502)."""
    q: queue.Queue = queue.Queue(maxsize=64)
    t = threading.Thread(target=_run_synth, args=(voice, text, q), daemon=True)
    t.start()
    first = True
    while True:
        item = q.get()
        if item is _SENTINEL:
            return
        if isinstance(item, Exception):
            if first:
                raise item
            return  # caiu no meio do stream: encerra o que deu
        first = False
        yield item


def _synthesize_full(voice: str, text: str) -> bytes:
    return b"".join(_synthesize(voice, text))


# --------------------------------------------------------------------------- #
# Helpers de conteúdo
# --------------------------------------------------------------------------- #

def _description_for(content_id: str) -> tuple[str, str]:
    """Retorna (nome, texto_a_ler) usando o mesmo critério da página:
    overview do TMDB > description da lista. '' se não houver."""
    item = database.get_content(content_id)
    if not item:
        return "", ""
    name = item.get("name") or ""
    meta = database.get_metadata(content_id) or {}
    overview = ((meta.get("tmdb") or {}).get("overview")) or ""
    text = overview or item.get("description") or ""
    text = " ".join(text.split())
    return name, text[:MAX_CHARS]


def _voice_for_lang(lang: str | None) -> str | None:
    if not lang:
        return None
    return VOICE_BY_LANG.get(lang.strip().lower())


# --------------------------------------------------------------------------- #
# Rotas
# --------------------------------------------------------------------------- #

@bp.get("/tts")
def tts_describe():
    content_id = request.args.get("id", "").strip()
    name, text = _description_for(content_id)
    if not text:
        return jsonify({"error": "sem descrição", "fallback": "browser"}), 404

    voice = _voice_for_lang(request.args.get("lang"))
    if not voice:
        # idioma sem voz neural pt/en/es... conhecida -> usa browser local
        return jsonify({"error": "idioma sem voz edge", "fallback": "browser"}), 501

    key = _cache_key(voice, text)
    cached = _cache_get(key)
    if cached is not None:
        return Response(
            cached,
            mimetype="audio/mpeg",
            headers={
                "Cache-Control": "private, max-age=21600",
                "X-Voice": voice,
                "X-TTS-Cache": "hit",
            },
        )

    try:
        import edge_tts  # noqa: F401
    except ImportError:
        return jsonify({"error": "edge-tts indisponível", "fallback": "browser"}), 502

    # Tenta sintetizar; falha no primeiro chunk -> 502 (frontend degrada).
    gen = _synthesize(voice, text)
    try:
        first_chunk = next(gen)
    except StopIteration:
        return jsonify({"error": "sintese vazia", "fallback": "browser"}), 502
    except Exception:  # noqa: BLE001
        return jsonify({"error": "edge-tts indisponivel", "fallback": "browser"}), 502

    def _stream():
        buf = bytearray()
        buf.extend(first_chunk)
        yield first_chunk
        try:
            for chunk in gen:
                buf.extend(chunk)
                yield chunk
            # stream completo: guarda cache
            _cache_put(key, bytes(buf))
        except Exception:  # noqa: BLE001
            pass

    return Response(
        _stream(),
        mimetype="audio/mpeg",
        headers={"X-Voice": voice, "Accept-Ranges": "none"},
    )
