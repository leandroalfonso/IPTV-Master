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
        // Mantém a classe base (display:flex do CSS centraliza o conteúdo);
        // esconder é só voltar com d-none. Antes "d-block" quebrava o centering.
        msg.className = "sv-player-msg";
        msg.dataset.kind = kind;
        msg.innerHTML = `<div class="sv-msg-icon"><i class="bi ${icon}"></i></div><div>${text}</div>`;
    }
    function showRetryBtn(label, href) {
        if (!msg) return;
        const a = document.createElement("a");
        a.className = "btn sv-btn-primary"; a.textContent = label; a.href = href;
        msg.appendChild(a);
    }
    function hideMsg() { if (msg) { msg.classList.add("d-none"); msg.innerHTML = ""; } }
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
            // Tuning para IPTV com segmentos LONGOS (8-12s):
            // - liveSyncDuration maior: ficar a 3s do edge ao vivo drena o
            //   buffer a cada variação de throughput -> stall constante. Com
            //   12s o player acumula folga e engole flutuação de rede.
            // - maxBufferLength 24s: lookahead suficiente para o próximo
            //   segmento de 12s estar pronto antes do atual acabar.
            // - maxBufferSize 96MB: sem isso o padrão (60MB) corta o buffer
            //   de comprimento antes em streams 4K.
            // - fragLoadingTimeOut 45s / maxRetry 8: abortar e recarregar um
            //   segmento de 12s lento custa mais que esperar; retries com
            //   timeout curto causavam o loop de stall.
            // - startFragPrefetch: baixa o 1º fragmento em paralelo com a
            //   montagem do SourceBuffer (startup mais rápido).
            hls = new window.Hls({
                enableWorker: true,
                lowLatencyMode: false,
                liveSyncDuration: isLive ? 12 : undefined,
                liveMaxLatencyDuration: isLive ? 40 : undefined,
                maxBufferLength: 24,
                maxMaxBufferLength: 60,
                backBufferLength: isLive ? 30 : 90,
                maxBufferSize: 96 * 1000 * 1000,
                fragLoadingTimeOut: 45000,
                fragLoadingMaxRetry: 8,
                fragLoadingRetryDelay: 500,
                fragLoadingMaxRetryTimeout: 8000,
                manifestLoadingTimeOut: 20000,
                manifestLoadingMaxRetry: 4,
                startFragPrefetch: true,
            });
            hls.loadSource(url);
            hls.attachMedia(video);
            window.__hls = hls; // handle de diagnóstico (console/devtools)

            hls.on(window.Hls.Events.MANIFEST_PARSED, () => {
                hideSpinner();
                // Duas esperas antes do play para eliminar stalls de arranque:
                // 1) ~2.5s de buffer (VOD e live): iniciar seco trava enquanto
                //    o 1o fragmento (8-12s) termina de chegar.
                // 2) live: o hls.js re-posiciona o video para o live edge
                //    (liveSyncPosition) logo apos o primeiro append. Se o play
                //    partir de t=0, esse seek interno causa um micro-stall de
                //    ~0.8s em seguida. Esperamos o currentTime ser movido (ou
                //    o seek em curso) antes de dar play.
                // Timeout de seguranca de 8s: se nada subir (origem lenta),
                // da play mesmo assim e o fluxo de erros existente cuida.
                const t0 = Date.now();
                const tryPlay = () => {
                    let buffered = 0;
                    try { buffered = video.buffered.length ? video.buffered.end(video.buffered.length - 1) : 0; } catch (e) {}
                    if (buffered >= 2.5 || Date.now() - t0 > 8000) {
                        // live: posicione ANTES do play no liveSyncPosition. Se o
                        // play partir de t=0, o hls.js re-busca a posicao de sync
                        // logo apos comecar (seek pos-play = stall de arranque).
                        if (isLive && hls && Number.isFinite(hls.liveSyncPosition)) {
                            const lsp = hls.liveSyncPosition;
                            const bufEnd = buffered;
                            if (Math.abs(video.currentTime - lsp) > 0.5 && (!bufEnd || lsp <= bufEnd + 0.2)) {
                                try { video.currentTime = lsp; } catch (e) {}
                            }
                        }
                        video.play().catch(() => showMsg("Clique em Play para iniciar a transmissão.", "bi-play-circle", "info"));
                    } else {
                        setTimeout(tryPlay, 250);
                    }
                };
                tryPlay();
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
            // Live nativo (Safari/iOS): começar no fim do buffer (~edge) e nao
            // em t=0. Em janela deslizante, t=0 sai do range bufferizado em
            // poucos segundos e o player sofre stall + salto forcado.
            if (isLive) {
                try {
                    const b = video.buffered;
                    if (b.length && b.end(b.length - 1) - b.start(0) > 12) {
                        video.currentTime = b.end(b.length - 1) - 6;
                    }
                } catch (e) {}
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
            const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
            if (fsEl) {
                const exit = document.exitFullscreen || document.webkitExitFullscreen;
                exit && exit.call(document);
                return;
            }
            // iPhone Safari nao expoe requestFullscreen no <video>: cai para o
            // fullscreen nativo (webkitEnterFullscreen) e, sem nenhum deles,
            // habilita os controles nativos como ultimo recurso.
            const req = video.requestFullscreen || video.webkitRequestFullscreen || video.webkitEnterFullscreen;
            if (!req) { video.controls = true; return; }
            try {
                const p = req.call(video);
                if (p && typeof p.catch === "function") p.catch(() => { video.controls = true; });
            } catch (e) { video.controls = true; }
        });
        seek && seek.addEventListener("input", () => {
            if (video.duration) video.currentTime = (seek.value / 100) * video.duration;
        });
        video.addEventListener("play", syncPlayIcon);
        video.addEventListener("pause", syncPlayIcon);
        video.addEventListener("timeupdate", updateSeek);
        // A mensagem de "autoplay bloqueado" e o spinner devem sumir assim que o
        // video realmente comeca a renderizar quadros — antes ela ficava fixa para
        // sempre sobre o player, mesmo apos o play funcionar.
        video.addEventListener("playing", () => {
            hideSpinner();
            if (msg && msg.dataset.kind === "info") hideMsg();
        });
        syncPlayIcon();

        if (btnPrev && cfg.prevId) btnPrev.onclick = () => { window.location.href = "/assistir/" + cfg.prevId; };
        if (btnNext && cfg.nextId) btnNext.onclick = () => { window.location.href = "/assistir/" + cfg.nextId; };
    }

    /* ---------- overlay de mensagem: clique inicia a reproducao ---------- */
    if (msg) {
        msg.addEventListener("click", (e) => {
            // Nao interceptar o botao "Tentar novamente" das mensagens de erro.
            if (e.target.closest("a")) return;
            if (msg.dataset.kind !== "info") return;
            video.play().catch(() => {});
        });
    }

    /* ---------- mobile: toque no video mostra/esconde a barra de controles ----------
       Em tela de toque nao existe :hover, entao a barra (opacity:0 por padrao) nunca
       aparecia. Um toque simples alterna a visibilidade; tocar 2x alterna o play. */
    const wrap = document.querySelector(".sv-player-wrap");
    const isTouch = window.matchMedia("(hover: none)").matches;
    let hideTimer = null;
    function showControls(autoHide = true) {
        if (!controls) return;
        controls.classList.add("sv-controls-show");
        clearTimeout(hideTimer);
        if (autoHide) hideTimer = setTimeout(() => {
            if (!video.paused) controls.classList.remove("sv-controls-show");
        }, 3500);
    }
    if (isTouch && wrap && controls) {
        let lastTap = 0;
        wrap.addEventListener("click", (e) => {
            // ignora toques nos proprios controles e no overlay de mensagem
            if (e.target.closest(".sv-controls") || e.target.closest(".sv-player-msg")) return;
            const now = Date.now();
            if (now - lastTap < 300) {
                video.paused ? video.play().catch(() => {}) : video.pause();
                clearTimeout(hideTimer);
            } else {
                controls.classList.contains("sv-controls-show")
                    ? controls.classList.remove("sv-controls-show")
                    : showControls();
            }
            lastTap = now;
        });
        video.addEventListener("play", () => showControls());
        video.addEventListener("pause", () => showControls(false));
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
        // timeupdate dispara a cada ~250ms: com setTimeout+clear dentro do
        // handler o timer NUNCA chegava a disparar (debounce invertido) e o
        // historico nunca era salvo. O certo e throttle: agenda UMA vez e
        // so agenda de novo depois de gravar.
        video.addEventListener("timeupdate", () => {
            if (saveTimer) return;
            saveTimer = setTimeout(() => { saveTimer = null; saveProgress(); }, 5000);
        });
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
