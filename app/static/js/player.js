/* =========================================================
   StreamVault — player.js
   Reprodução de canais ao vivo e VOD no navegador.

   - Uma única instância HLS.js (destruída ao trocar de canal).
   - Suporte nativo (Safari/iOS) quando disponível.
   - Proxy de HLS no backend elimina o bloqueio de CORS da origem.
   - Controles customizados: play/pause, seek, mute, PiP, fullscreen,
     canal anterior/próximo, atalhos de teclado.
   - Tratamento de erros com taxonomia (rede/mídia/manifest/segmento).
   ========================================================= */
(() => {
    "use strict";

    const cfg = window.SV_STREAM;
    if (!cfg || !cfg.url) return;

    const video = document.getElementById("svVideo");
    const spinner = document.getElementById("svSpinner");
    const msg = document.getElementById("svMsg") || document.getElementById("svPlayerMsg");
    const isLive = cfg.type === "live";

    const streamUrl = cfg.streamUrl || cfg.url;
    let hls = null;

    /* ---------- helpers de UI ---------- */
    function showMsg(text, icon = "bi-exclamation-triangle", kind = "error") {
        if (!msg) return;
        msg.className = "sv-player-msg d-block";
        msg.innerHTML = `<div class="sv-msg-icon"><i class="bi ${icon}"></i></div><div>${text}</div>`;
    }
    function showRetryBtn(label, href) {
        if (!msg) return;
        const a = document.createElement("a");
        a.className = "btn sv-btn-primary"; a.textContent = label; a.href = href;
        msg.appendChild(a);
    }
    function hideMsg() { if (msg) msg.classList.add("d-none"); }
    function showSpinner() { if (spinner) spinner.style.display = "flex"; }
    function hideSpinner() { if (spinner) spinner.style.display = "none"; }

    const log = (...a) => console.log("[StreamVault]", ...a);
    const logErr = (...a) => console.error("[StreamVault]", ...a);

    /* ---------- diagnóstico da URL ---------- */
    function analisarStream(url) {
        if (!url) return { valido: false, erro: "URL não informada" };
        const u = url.split("?")[0].toLowerCase();
        if (u.endsWith(".m3u8")) return { valido: true, tipo: "hls" };
        if (u.endsWith(".mp4") || u.endsWith(".m4v") || u.endsWith(".webm")) return { valido: true, tipo: "mp4" };
        return { valido: true, tipo: "desconhecido" };
    }

    /* ---------- destruir player anterior ---------- */
    function destruirPlayer() {
        if (hls) { hls.destroy(); hls = null; log("Instância HLS.js anterior destruída."); }
        try { video.pause(); video.removeAttribute("src"); video.load(); } catch (e) {}
    }

    /* ---------- tocar via HLS.js ---------- */
    function carregarHlsJs(url) {
        destruirPlayer();
        showSpinner(); hideMsg();

        if (window.Hls && window.Hls.isSupported()) {
            hls = new window.Hls({
                enableWorker: true, lowLatencyMode: isLive,
                liveSyncDuration: isLive ? 3 : undefined,
                fragLoadingMaxRetry: 6, manifestLoadingMaxRetry: 4,
                backBufferLength: isLive ? 30 : 90,
            });
            hls.loadSource(url);
            hls.attachMedia(video);

            hls.on(window.Hls.Events.MANIFEST_PARSED, () => {
                hideSpinner();
                video.play().catch(() => showMsg("Clique em Play para iniciar a transmissão.", "bi-play-circle", "info"));
            });
            hls.on(window.Hls.Events.ERROR, (evt, data) => {
                logErr("Erro HLS:", data);
                if (!data || !data.fatal) return;
                switch (data.type) {
                    case window.Hls.ErrorTypes.NETWORK_ERROR:
                        showMsg("Erro de rede ao carregar. Tentando reconectar...");
                        hls.startLoad(); break;
                    case window.Hls.ErrorTypes.MEDIA_ERROR:
                        showMsg("Erro de mídia. Tentando recuperar...");
                        hls.recoverMediaError(); break;
                    default:
                        destruirPlayer();
                        showMsg(isLive ? "Canal temporariamente indisponível." : "Não foi possível reproduzir este conteúdo.", "bi-exclamation-triangle");
                        showRetryBtn("Tentar novamente", window.location.href);
                }
            });
        } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
            carregarNativo(url);
        } else {
            showMsg("Este navegador não suporta este formato de transmissão.", "bi-x-circle");
        }
    }

    /* ---------- tocar via <video> nativo ---------- */
    function carregarNativo(url) {
        destruirPlayer();
        showSpinner(); hideMsg();
        video.src = url;
        video.addEventListener("loadedmetadata", () => {
            hideSpinner();
            if (!isLive && cfg.start && cfg.start > 1) {
                try { video.currentTime = Math.min(cfg.start, video.duration || cfg.start); } catch (e) {}
            }
            video.play().catch(() => showMsg("Clique em Play para iniciar.", "bi-play-circle", "info"));
        }, { once: true });
        video.addEventListener("error", () => {
            const code = video.error && video.error.code;
            logErr("Erro de vídeo nativo. code=", code);
            if (code === 2 || code === 4) showMsg("Canal temporariamente indisponível ou formato não suportado.", "bi-exclamation-triangle");
            else showMsg("Não foi possível reproduzir este canal.", "bi-exclamation-triangle");
        });
    }

    function carregarCanal(url) {
        const info = analisarStream(url);
        log("Canal:", cfg.name, "| URL:", url, "| isHls:", cfg.isHls, "| tipo:", info.tipo);
        if (!info.valido) { showMsg("URL do canal inválida: " + info.erro); return; }
        // HLS (independentemente de ser ao vivo ou VOD) passa pelo proxy/HLS.js.
        if (cfg.isHls) {
            if (video.canPlayType("application/vnd.apple.mpegurl")) carregarNativo(url);
            else carregarHlsJs(url);
        } else {
            // Mídia direta (mp4/mkv/webm): o proxy agora serve com CORS + Range,
            // então nativo funciona sem bloqueio de CORS da origem.
            carregarNativo(url);
        }
    }

    /* =====================================================
       CONTROLES CUSTOMIZADOS
       ===================================================== */
    const controls = document.getElementById("svControls");
    const btnPlay = document.querySelector(".sv-playpause");
    const btnMute = document.querySelector(".sv-mute");
    const btnPip = document.querySelector(".sv-pip");
    const btnFull = document.querySelector(".sv-full");
    const btnPrev = document.querySelector(".sv-prev");
    const btnNext = document.querySelector(".sv-next");
    const seek = document.getElementById("svSeek");
    const timeLabel = document.getElementById("svTime");

    function fmt(t) {
        if (!t || isNaN(t)) return "0:00";
        t = Math.floor(t);
        const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
        return (h ? h + ":" : "") + String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
    }
    function syncPlayIcon() {
        if (!btnPlay) return;
        const i = btnPlay.querySelector("i");
        i.className = video.paused ? "bi bi-play-fill" : "bi bi-pause-fill";
    }
    function updateSeek() {
        if (isLive || !seek) return;
        if (video.duration) {
            seek.value = (video.currentTime / video.duration) * 100;
            if (timeLabel) timeLabel.textContent = fmt(video.currentTime) + " / " + fmt(video.duration);
        }
    }

    if (controls) {
        btnPlay && btnPlay.addEventListener("click", () => { video.paused ? video.play() : video.pause(); });
        btnMute && btnMute.addEventListener("click", () => {
            video.muted = !video.muted;
            const i = btnMute.querySelector("i");
            i.className = video.muted ? "bi bi-volume-mute-fill" : "bi bi-volume-up-fill";
        });
        btnPip && btnPip.addEventListener("click", async () => {
            try {
                if (document.pictureInPictureElement) await document.exitPictureInPicture();
                else if (video.requestPictureInPicture) await video.requestPictureInPicture();
            } catch (e) { log("PiP indisponível:", e.message); }
        });
        btnFull && btnFull.addEventListener("click", () => {
            if (!document.fullscreenElement) video.requestFullscreen?.();
            else document.exitFullscreen?.();
        });
        seek && seek.addEventListener("input", () => {
            if (video.duration) video.currentTime = (seek.value / 100) * video.duration;
        });
        video.addEventListener("play", syncPlayIcon);
        video.addEventListener("pause", syncPlayIcon);
        video.addEventListener("timeupdate", updateSeek);
        syncPlayIcon();

        if (btnPrev && cfg.prevId) btnPrev.onclick = () => { window.location.href = "/assistir/" + cfg.prevId; };
        if (btnNext && cfg.nextId) btnNext.onclick = () => { window.location.href = "/assistir/" + cfg.nextId; };
    }

    /* ---------- atalhos de teclado ---------- */
    document.addEventListener("keydown", (e) => {
        if (/INPUT|TEXTAREA/.test(document.activeElement?.tagName || "")) return;
        switch (e.key) {
            case " ": case "Spacebar": e.preventDefault(); video.paused ? video.play() : video.pause(); break;
            case "f": case "F": btnFull && btnFull.click(); break;
            case "m": case "M": btnMute && btnMute.click(); break;
            case "Escape":
                if (document.fullscreenElement) document.exitFullscreen?.();
                if (msg) msg.classList.add("d-none");
                break;
            case "ArrowRight": if (!isLive) video.currentTime += 10; break;
            case "ArrowLeft": if (!isLive) video.currentTime -= 10; break;
        }
    });

    /* ---------- salvar progresso ("Continuar assistindo") — só VOD ---------- */
    if (!isLive) {
        let saveTimer;
        const saveProgress = () => {
            if (!video.duration || video.duration === 0) return;
            const position = video.currentTime;
            if (position < 2) return;
            fetch("/api/history", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    content_id: cfg.id, content_type: cfg.type,
                    name: cfg.name, logo: cfg.logo,
                    position: position, duration: video.duration,
                }),
            }).catch(() => {});
        };
        video.addEventListener("timeupdate", () => { clearTimeout(saveTimer); saveTimer = setTimeout(saveProgress, 5000); });
        video.addEventListener("pause", saveProgress);
        video.addEventListener("ended", () => {
            fetch("/api/history", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ content_id: cfg.id, content_type: cfg.type, name: cfg.name, logo: cfg.logo, position: video.duration, duration: video.duration }),
            }).catch(() => {});
        });
    }

    // Segurança: esconde spinner se algo travar.
    setTimeout(() => hideSpinner(), 15000);

    carregarCanal(streamUrl);
})();
