/* =========================================================
   StreamVault — cast.js
   Google Cast / Chromecast — botão de transmitir para TV.

   Depende de:
     - window.SV_CAST_MEDIA  (definido no template assistir.html)
     - SDK do Cast carregado no <head> do assistir.html
     - Botão #svCastBtn nos controles do player
   ========================================================= */
(() => {
    "use strict";

    const media = window.SV_CAST_MEDIA;
    const btn = document.getElementById("svCastBtn");
    if (!media || !btn) return;

    /* ---------- auxiliares ---------- */
    const log = (...a) => console.log("[StreamVault Cast]", ...a);
    let context = null;

    /* ---------- montar URL absoluta para a TV ---------- */
    async function toAbsolute(path) {
        if (!path) return "";
        if (/^https?:\/\//i.test(path)) return path;
        let host = location.hostname;
        if (host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0") {
            try {
                const r = await fetch("/api/local-ip");
                const j = await r.json();
                if (j.ip) host = j.ip;
            } catch (e) { /* fallback para hostname */ }
        }
        const port = location.port ? ":" + location.port : "";
        return location.protocol + "//" + host + port + path;
    }

    /* ---------- carregar mídia na sessão Cast ---------- */
    function loadMedia() {
        const session = context.getCurrentSession();
        if (!session) return;
        toAbsolute(media.url).then(url => {
            const info = new chrome.cast.media.MediaInfo(
                url,
                media.contentType || "video/mp4"
            );
            info.metadata = new chrome.cast.media.GenericMediaMetadata();
            info.metadata.title = media.title || "StreamVault";
            if (media.poster) {
                toAbsolute(media.poster).then(posterUrl => {
                    if (posterUrl) {
                        try {
                            info.metadata.images = [{ url: posterUrl }];
                        } catch (e) { /* ignora erro de poster */ }
                    }
                    session.loadMedia(new chrome.cast.media.LoadRequest(info))
                        .then(() => log("Transmitindo:", media.title))
                        .catch(err => log("Erro loadMedia:", err));
                });
            } else {
                session.loadMedia(new chrome.cast.media.LoadRequest(info))
                    .then(() => log("Transmitindo:", media.title))
                    .catch(err => log("Erro loadMedia:", err));
            }
        });
    }

    /* ---------- estado do botão ---------- */
    function setActive(active) {
        btn.classList.toggle("sv-cast-active", active);
        btn.title = active ? "Desconectar da TV" : "Transmitir para TV";
        const icon = btn.querySelector("i");
        if (icon) icon.className = active ? "bi bi-cast-fill" : "bi bi-cast";
    }

    /* ---------- callback de mudança de estado ---------- */
    function onCastStateChanged() {
        if (!context) return;
        const st = context.getCastState();
        const session = context.getCurrentSession();
        setActive(st === cast.framework.CastState.CONNECTED);
        if (st === cast.framework.CastState.CONNECTED && session) {
            loadMedia();
        }
    }

    /* ---------- inicializar Cast SDK ---------- */
    function init() {
        if (!window.chrome || !window.chrome.cast) {
            log("Cast SDK não disponível");
            return;
        }
        try {
            context = cast.framework.CastContext.getInstance();
            context.setOptions({
                receiverApplicationId: window.SV_CAST_APP_ID || "CC1AD845",
                autoJoinPolicy: chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED,
            });
            context.addEventListener(
                cast.framework.CastContextEventType.CAST_STATE_CHANGED,
                onCastStateChanged
            );
            // Mostra o botão e sincroniza estado inicial
            btn.style.display = "";
            onCastStateChanged();

            // Click: conecta ou desconecta
            btn.addEventListener("click", () => {
                const st = context.getCastState();
                if (st === cast.framework.CastState.CONNECTED) {
                    context.endCurrentSession(true);
                } else {
                    context.requestSession().catch(() => {});
                }
            });
            log("Cast inicializado (receiver: CC1AD845)");
        } catch (e) {
            log("Erro ao inicializar Cast:", e.message);
        }
    }

    /* ---------- hook do SDK ---------- */
    window.__onGCastApiAvailable = function (isAvailable) {
        if (isAvailable) init();
    };

    // Fallback: se o SDK já estava carregado antes deste script
    if (window.chrome && window.chrome.cast && window.chrome.cast.isAvailable) {
        init();
    }
})();