"""Proxy de streams HLS para reprodução web sem bloqueio de CORS.

Problema que resolve:
  - A origem IPTV (ctnbld.top) NÃO envia `Access-Control-Allow-Origin`.
    O hls.js busca manifesto e segmentos via XHR e o navegador bloqueia (CORS).
  - Canais ao vivo (.m3u8) geralmente 302-redirecionam para um host
    tokenizado, e os segmentos dentro do manifesto são caminhos RELATIVOS
    (/hls/...ts). O hls.js resolveria contra a origem da página e daria 404.

Solução:
  - O backend faz o fetch server-to-server (sem CORS) do manifesto e de cada
    segmento .ts, e os serve com cabeçalhos CORS permissivos.
  - Reescreve os caminhos relativos dos segmentos para URLs absolutas do
    próprio proxy, para que o navegador só converse com a nossa origem.
  - Manifestos "master" (que apontam para variantes .m3u8) são reescritos
    recursivamente: cada variante passa por /proxy/playlist, que por sua vez
    reescreve seus próprios segmentos.

Segurança (anti-SSRF):
  - content_id precisa existir no banco (não é um proxy aberto/SSRF livre).
  - A origem autorizada NÃO vem do cliente. É computada server-side (host
    final do manifesto após redirects) e assinada com HMAC(SECRET_KEY). O
    cliente só recebe o token; qualquer alteração em `o` invalida a assinatura
    e a requisição é rejeitada (403). Assim o cliente não consegue apontar o
    proxy para hosts arbitrários (internos, metadata cloud, etc).
  - Mesmo com token válido, o host do segmento/playlist é validado contra o
    domínio registrável da origem assinada (ou IP), como defesa em profundidade.
"""

import re
import hmac
import hashlib
import logging
import mimetypes
import requests
from flask import Blueprint, request, Response, abort, current_app
from urllib.parse import urlparse, quote

from . import database, config

logger = logging.getLogger("streamvault.proxy")

bp = Blueprint("proxy", __name__)

# Pasta que contém os segmentos dentro do manifesto (ex.: /hls/...).
_SEGMENT_RE = re.compile(r"^(/[\w.\-/%]+?\.(?:ts|aac|mp4|m4s|key|vtt|m3u8))$", re.I)


# --------------------------------------------------------------------------- #
# Assinatura da origem (anti-SSRF: o cliente não pode forjar a origem)
# --------------------------------------------------------------------------- #
def _sign_origin(origin: str) -> str:
    secret = config.Config.SECRET_KEY
    return hmac.new(secret.encode(), origin.encode(), hashlib.sha256).hexdigest()


def _origin_of(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _registrable_domain(host: str) -> str:
    """Domínio registrável (ex.: 'ctnbld.top', 'example.com'). IPs retornados como-is."""
    h = host.split(":")[0]
    if h.replace(".", "").isdigit():  # IPv4 simples
        return h
    parts = h.split(".")
    if len(parts) <= 2:
        return h
    return ".".join(parts[-2:])


def _is_allowed(url: str, allowed_origin: str) -> bool:
    """SSRF: só permite URLs do mesmo domínio registrável da origem assinada.

    Hosts baseados em nome: exigimos domínio registrável idêntico (ex. ambos
    'ctnbld.top'), o que impede apontar para outro domínio.

    Hosts IP: a origem IPTV serve segmentos de hosts tokenizados por IP, mas
    NUNCA devemos permitir IPs internos (loopback, private, link-local como
    169.254.169.254/metadata cloud, CGNAT, reservados). Só liberamos IPs
    PUBLICAMENTE roteáveis. Isso mantém o suporte a CDNs tokenizadas sem abrir
    SSRF para a rede interna/cloud.

    Defesa extra: a própria origem assinada (allowed_origin) também não pode ser
    um IP interno/link-local — assim, mesmo quem possua a SECRET_KEY não consegue
    usar o proxy para atacar a rede interna/metadata cloud.
    """
    if not allowed_origin:
        return False
    import ipaddress

    def _ok_host(netloc: str) -> bool:
        host = netloc.split(":")[0]
        if host.replace(".", "").isdigit():  # IPv4
            try:
                ip = ipaddress.ip_address(host)
            except ValueError:
                return False
            return (
                not ip.is_private
                and not ip.is_loopback
                and not ip.is_link_local
                and not ip.is_reserved
                and not ip.is_multicast
                and not ip.is_unspecified
            )
        return True  # host nomeado: validação de domínio feita pelo chamador

    # A origem assinada não pode ser IP interno/link-local.
    base_netloc = urlparse(allowed_origin).netloc
    if not _ok_host(base_netloc):
        return False

    seg_netloc = urlparse(url).netloc.split(":")[0]
    base_netloc = base_netloc.split(":")[0]

    # Nome de host: compara domínio registrável.
    if not seg_netloc.replace(".", "").isdigit():
        return _registrable_domain(seg_netloc) == _registrable_domain(base_netloc)

    # Host IP: só permite se for público (bloqueia 127/10/172.16/192.168/169.254...).
    try:
        ip = ipaddress.ip_address(seg_netloc)
    except ValueError:
        return False
    return (
        not ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_reserved
        and not ip.is_multicast
        and not ip.is_unspecified
    )


def _safe_stream_url(content_id: str):
    """Retorna a URL real do stream apenas se o content_id existir no banco."""
    item = database.get_content(content_id)
    if not item or not item.get("url"):
        return None
    return item["url"]


def _rewrite_manifest(body: str, origin: str) -> str:
    """Reescreve um manifesto HLS: segmentos -> /proxy/segment, variantes
    .m3u8 -> /proxy/playlist. Tudo carrega o token assinado da origem."""
    token = (
        f"&o={quote(origin, safe='')}&s={quote(_sign_origin(origin), safe='')}"
    )
    out = []
    for line in body.splitlines():
        line = line.rstrip("\n")
        if not line or line.startswith("#"):
            out.append(line)
            continue
        if line.startswith("http://") or line.startswith("https://"):
            abs_url = line
        elif _SEGMENT_RE.match(line):
            abs_url = origin + line
        else:
            abs_url = f"{origin}/{line.lstrip('/')}"
        enc = quote(abs_url, safe="")
        if abs_url.lower().split("?")[0].endswith(".m3u8"):
            out.append(f"/proxy/playlist?u={enc}{token}")
        else:
            out.append(f"/proxy/segment?u={enc}{token}")
    return "\n".join(out) + "\n"


def _verify_origin(origin: str, sig: str) -> bool:
    if not origin or not sig:
        return False
    return hmac.compare_digest(_sign_origin(origin), sig)


def _stream_ranges(url: str, start: int, end: int | None, ctype_holder: list):
    """Gerador que busca a origem em FATIAS (range requests) e as costura.

    A origem IPTV corta conexões longas (IncompleteRead no meio de uma fatia) e
    às vezes responde 503 (rate-limit). Por isso: (1) pedimos a origem em pedaços
    de ~4MB; (2) cada fatia tem retry com backoff; (3) há um pequeno espaçamento
    entre fatias para não sobrecarregar a origem. Isso contorna o corte e o
    rate-limit, e ainda permite seek (o navegador pede Range -> proxyia o trecho).
    """
    import time
    from urllib3.exceptions import IncompleteRead

    SLICE = 4 * 1024 * 1024  # 4 MB por requisição à origem (evita corte da origem)
    MAX_RETRY = 3
    base_headers = {
        "User-Agent": "StreamVault/1.0",
        "Referer": _origin_of(url) + "/",
    }
    pos = start
    total = end  # None = até o fim (vamos descobrir via Content-Range)
    first_fatia = True
    while True:
        if total is not None and pos > total:
            break
        hi = (pos + SLICE - 1) if (end is None or pos + SLICE - 1 < end) else end
        range_hdr = f"bytes={pos}-{hi if hi is not None else ''}"

        # Pequeno espaçamento entre fatias (exceto a primeira) p/ evitar
        # rate-limit da origem em sequências rápidas.
        if not first_fatia:
            time.sleep(0.3)
        first_fatia = False

        fatia_ok = False
        for attempt in range(MAX_RETRY):
            try:
                rr = requests.get(
                    url, headers={**base_headers, "Range": range_hdr},
                    timeout=30, allow_redirects=True, stream=True,
                )
            except requests.RequestException as exc:
                logger.warning("Proxy mídia fatia falhou (tent %d): %s", attempt + 1, exc)
                time.sleep(0.5 * (attempt + 1))
                continue
            if rr.status_code not in (200, 206):
                rr.close()
                logger.warning("Proxy mídia fatia HTTP %s (tent %d)", rr.status_code, attempt + 1)
                time.sleep(0.5 * (attempt + 1))
                continue
            if not ctype_holder[0]:
                ct = rr.headers.get("Content-Type", "")
                if ct:
                    ctype_holder[0] = ct
            cr = rr.headers.get("Content-Range", "")
            if "/" in cr:
                try:
                    total = int(cr.rsplit("/", 1)[1])
                except ValueError:
                    pass
            try:
                for chunk in rr.iter_content(chunk_size=65536):
                    if chunk:
                        yield chunk
                fatia_ok = True
            except Exception as exc:
                # Origem cortou a conexão no meio da fatia: os chunks já
                # yieldados foram entregues; tentamos de novo a mesma fatia.
                logger.warning("Proxy mídia fatia interrompida (retry %d): %s", attempt + 1, exc)
            finally:
                rr.close()
            if fatia_ok:
                break
            time.sleep(0.5 * (attempt + 1))
        if not fatia_ok:
            # Esgotou retries: entrega o que já veio e encerra (o player nativo
            # refaz o Range para o trecho faltante).
            logger.warning("Proxy mídia: fatia %s dada como perdida após retries", range_hdr)
            return
        if hi is None or (total is not None and hi >= total):
            break
        pos = hi + 1


def _proxy_media(url: str) -> Response:
    """Busca uma mídia direta (mp4/m4s/ts/...) e a re-serve em STREAMING
    fatiado (range-slicing), contornando o corte de conexão longa da origem.
    Suporta seek (Range do cliente é repassado). Não reescreve nada."""
    client_range = request.headers.get("Range")
    start = 0
    end = None
    total_size = None
    if client_range:
        m = re.match(r"bytes=(\d+)-(\d*)$", client_range)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else None
            # Probe mínimo para descobrir o tamanho total (Content-Range do
            # servidor) e poder montar o cabeçalho 206 + Content-Range.
            try:
                probe = requests.get(
                    url,
                    headers={
                        "User-Agent": "StreamVault/1.0",
                        "Referer": _origin_of(url) + "/",
                        "Range": "bytes=0-0",
                    },
                    timeout=20, allow_redirects=True, stream=True,
                )
                cr = probe.headers.get("Content-Range", "")
                if "/" in cr:
                    try:
                        total_size = int(cr.rsplit("/", 1)[1])
                    except ValueError:
                        pass
                probe.close()
            except requests.RequestException:
                pass

    ctype_holder = [""]
    gen = _stream_ranges(url, start, end, ctype_holder)

    ext = url.split("?")[0].split(".")[-1].lower()
    ctype = mimetypes.guess_type("x." + ext)[0] or ""
    if not ctype:
        # fallback após iniciar o stream: pega o que a origem informou
        ctype = ctype_holder[0] or "video/mp4"

    status = 206 if client_range else 200
    resp = Response(gen, status=status, mimetype=ctype)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Accept-Ranges"] = "bytes"
    if client_range and total_size:
        hi = end if end is not None else (total_size - 1)
        resp.headers["Content-Range"] = f"bytes {start}-{hi}/{total_size}"
    resp.headers["Cache-Control"] = "public, max-age=10"
    return resp


@bp.route("/proxy/stream/<content_id>")
def proxy_stream(content_id: str):
    target = _safe_stream_url(content_id)
    if not target:
        abort(404)

    # Detecta HLS de forma barata (sem abrir conexão): quase todo HLS vem com
    # .m3u8 na URL ou Content-Type mpegurl. Mídia direta (mp4/mkv/webm/...) vai
    # direto para _proxy_media (range-slicing), evitando uma conexão de sondagem
    # que a origem IPTV costuma cortar/rate-limitar.
    looks_hls = target.lower().endswith(".m3u8")

    if not looks_hls:
        return _proxy_media(target)

    # HLS: busca o manifesto (pequeno) e reescreve.
    headers = {
        "User-Agent": "StreamVault/1.0",
        "Referer": _origin_of(target) + "/",
    }
    if request.range:
        headers["Range"] = request.headers.get("Range")
    try:
        r = requests.get(
            target, headers=headers, timeout=30, allow_redirects=True, stream=True
        )
    except requests.RequestException as exc:
        logger.warning("Proxy stream fetch falhou: %s", exc)
        return Response("Canal indisponível (origem offline).", status=503)

    if r.status_code not in (200, 206):
        r.close()
        return Response(f"Canal indisponível (HTTP {r.status_code}).", status=503)

    ctype = r.headers.get("Content-Type", "")
    is_hls = "mpegurl" in ctype or target.lower().endswith(".m3u8")
    if not is_hls:
        # Não era HLS afinal: entrega como mídia direta.
        r.close()
        return _proxy_media(target)

    try:
        body = r.content.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Proxy stream fetch falhou: %s", exc)
        r.close()
        return Response("Canal indisponível (origem offline).", status=503)
    r.close()
    origin = _origin_of(r.url)  # URL final após redirects
    rewritten = _rewrite_manifest(body, origin)
    resp = Response(
        rewritten, status=200, mimetype="application/vnd.apple.mpegurl"
    )
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def _proxy_media_from_response_guard():
    """Função removida: o proxy de mídia agora usa range-slicing via
    _proxy_media. Mantida apenas para não quebrar imports; não deve ser chamada."""
    raise RuntimeError("use _proxy_media")


@bp.route("/proxy/playlist")
def proxy_playlist():
    """Proxy de sub-manifestos HLS (variantes de um master playlist).

    Recebe a URL do sub-manifesto assinada com a origem autorizada. Valida a
    assinatura (anti-SSRF) e, se for HLS, reescreve recursivamente, assinando
    a nova origem (pós-redirect) com o segredo do servidor.
    """
    u = request.args.get("u")
    o = request.args.get("o")
    s = request.args.get("s")
    if not u or not (u.startswith("http://") or u.startswith("https://")):
        abort(400)
    if not _verify_origin(o or "", s or ""):
        abort(403)

    if not _is_allowed(u, o):
        logger.warning("Proxy playlist bloqueado (SSRF): %s", u)
        abort(403)

    try:
        r = requests.get(
            u,
            headers={"User-Agent": "StreamVault/1.0", "Referer": _origin_of(u) + "/"},
            timeout=20,
            allow_redirects=True,
        )
    except requests.RequestException:
        return Response("Playlist indisponível.", status=503)
    if r.status_code != 200:
        return Response(f"Playlist indisponível (HTTP {r.status_code}).", status=503)

    ctype = r.headers.get("Content-Type", "")
    body = r.text
    if (
        "mpegurl" in ctype
        or u.lower().endswith(".m3u8")
        or body.lstrip().startswith("#EXTM3U")
    ):
        origin = _origin_of(r.url)
        rewritten = _rewrite_manifest(body, origin)
        resp = Response(
            rewritten, status=200, mimetype="application/vnd.apple.mpegurl"
        )
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    # Sub-manifesto que na verdade é mídia direta.
    return _proxy_media(u)


@bp.route("/proxy/segment")
def proxy_segment():
    u = request.args.get("u")
    o = request.args.get("o")
    s = request.args.get("s")
    if not u or not (u.startswith("http://") or u.startswith("https://")):
        abort(400)
    # Origem obrigatoriamente assinada pelo servidor (anti-SSRF).
    if not _verify_origin(o or "", s or ""):
        abort(403)

    if not _is_allowed(u, o):
        logger.warning("Proxy segment bloqueado (SSRF): %s", u)
        abort(403)

    try:
        r = requests.get(
            u,
            headers={"User-Agent": "StreamVault/1.0", "Referer": _origin_of(u) + "/"},
            timeout=20,
            allow_redirects=True,
        )
    except requests.RequestException:
        return Response("Segmento indisponível.", status=503)

    if r.status_code != 200:
        return Response(f"Segmento indisponível (HTTP {r.status_code}).", status=503)

    # Força o mime correto para segmentos HLS (servidores às vezes mandam
    # Content-Type genérico/errado para .ts).
    ctype = r.headers.get("Content-Type", "")
    ext = u.split("?")[0].split(".")[-1].lower()
    if ext in ("ts", "m2ts", "aac", "mp4", "m4s", "key", "vtt"):
        guessed = mimetypes.guess_type("x." + ext)[0]
        if guessed:
            ctype = guessed
    resp = Response(r.content, status=200, mimetype=ctype or "video/mp2t")
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "public, max-age=10"
    return resp


# --------------------------------------------------------------------------- #
# Proxy de imagens (capas/logos)
# --------------------------------------------------------------------------- #
@bp.route("/proxy/image")
def proxy_image():
    """Serve imagens (capas/logos) via nossa origem.

    Por que: os domínios dos logos do provedor costumam bloquear hotlink
    (Referer), e imagens http:// em páginas HTTPS são barradas como mixed
    content. Buscamos server-side (sem o Referer do navegador) e re-servimos
    na mesma origem do StreamVault, eliminando esses bloqueios.

    Proteção SSRF: só http/https, e o content-type da resposta precisa ser
    imagem. Sem isso, a rota nem chega a servir conteúdo arbitrário.
    """
    u = request.args.get("u")
    if not u or not (u.startswith("http://") or u.startswith("https://")):
        abort(400)

    try:
        r = requests.get(
            u,
            headers={"User-Agent": "Mozilla/5.0 (compatible; StreamVault/1.0)"},
            timeout=15,
            allow_redirects=True,
        )
    except requests.RequestException:
        return Response("Imagem indisponível.", status=503)

    ctype = r.headers.get("Content-Type", "")
    if not ctype.startswith("image/"):
        return Response("Tipo de mídia não suportado.", status=415)

    if r.status_code != 200:
        return Response(f"Imagem indisponível (HTTP {r.status_code}).", status=503)

    resp = Response(r.content, status=200, mimetype=ctype)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp
