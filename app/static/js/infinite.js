/* =========================================================
   StreamVault — infinite.js
   Rolagem infinita para /canais, /filmes e /series.
   Usa IntersectionObserver + a API /api/contents e /api/series.
   Não altera o layout: gera o mesmo card dos templates.
   ========================================================= */
(function () {
    "use strict";

    const PAGE_SIZE = 24;

    // ---- Geradores de card (espelham os templates) ----
    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"]/g, c =>
            ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    }

    function imgTag(logo, alt) {
        if (!logo) return "";
        return `<img loading="lazy" src="/proxy/image?u=${encodeURIComponent(logo)}" alt="${esc(alt)}" referrerpolicy="no-referrer" onerror="this.style.display='none'">`;
    }

    // Metadado do card de filme: ano · gênero · nota (TMDB quando disponível,
    // senão a categoria da lista IPTV). Espelha o macro movie_card do template.
    function movieMeta(m) {
        const genre = (m.genres && m.genres[0]) || m.category || "";
        return [m.year, genre, m.rating ? "★ " + m.rating : ""].filter(Boolean).join(" · ");
    }

    function liveCard(c) {
        return `<div class="col-6 col-sm-4 col-md-3 col-lg-2 sv-col" data-cat="${esc(c.category)}">
            <div class="sv-card" data-id="${esc(c.id)}">
                <a href="/assistir/${esc(c.id)}" class="sv-card-link">
                    <div class="sv-thumb sv-thumb-live">
                        ${imgTag(c.logo, c.name)}
                        <div class="sv-thumb-fallback"><i class="bi bi-tv"></i></div>
                        <span class="sv-live-badge"><i class="bi bi-record-circle"></i> AO VIVO</span>
                        <div class="sv-card-overlay">
                            <a href="/assistir/${esc(c.id)}" class="sv-play-btn"><i class="bi bi-play-fill"></i></a>
                        </div>
                    </div>
                    <div class="sv-card-title">${esc(c.name)}</div>
                    <div class="sv-card-sub">${esc(c.group_name)}</div>
                </a>
            </div>
        </div>`;
    }

    function movieCard(m) {
        return `<div class="col-6 col-sm-4 col-md-3 col-lg-2 sv-col" data-cat="${esc(m.category)}">
            <div class="sv-card" data-id="${esc(m.id)}">
                <a href="/detalhes/${esc(m.id)}" class="sv-card-link">
                    <div class="sv-thumb">
                        ${imgTag(m.logo, m.name)}
                        <div class="sv-thumb-fallback"><i class="bi bi-film"></i></div>
                        <div class="sv-card-overlay">
                            <a href="/assistir/${esc(m.id)}" class="sv-play-btn"><i class="bi bi-play-fill"></i></a>
                            <button class="sv-fav-btn sv-fav" data-id="${esc(m.id)}" data-type="movie" data-name="${esc(m.name)}" data-logo="${esc(m.logo)}" data-url="${esc(m.url)}"><i class="bi bi-plus"></i></button>
                        </div>
                    </div>
                    <div class="sv-card-title">${esc(m.name)}</div>
                    <div class="sv-card-sub">${esc(movieMeta(m))}</div>
                </a>
            </div>
        </div>`;
    }

    function seriesCard(s) {
        const name = s.series_name;
        return `<div class="col-6 col-sm-4 col-md-3 col-lg-2">
            <div class="sv-card" data-series="${esc(name)}">
                <a href="/detalhes-series/${encodeURIComponent(name)}" class="sv-card-link">
                    <div class="sv-thumb">
                        ${imgTag(s.logo, name)}
                        <div class="sv-thumb-fallback"><i class="bi bi-collection-play"></i></div>
                        <div class="sv-card-overlay">
                            <a href="/detalhes-series/${encodeURIComponent(name)}" class="sv-play-btn"><i class="bi bi-play-fill"></i></a>
                        </div>
                    </div>
                    <div class="sv-card-title">${esc(name)}</div>
                    <div class="sv-card-sub">${esc(s.eps)} episódios</div>
                </a>
            </div>
        </div>`;
    }

    // ---- Lógica de rolagem infinita por página ----
    function setup(type) {
        const grid = document.getElementById(type === "live" ? "liveGrid" : type === "movie" ? "movieGrid" : "seriesGrid");
        if (!grid) return;

        let page = 1;
        let loading = false;
        let done = false;
        let activeCat = "";

        // Respeita o filtro de categoria (chips) se existir.
        const catChips = document.getElementById("catChips");
        if (catChips) {
            catChips.addEventListener("click", (e) => {
                const chip = e.target.closest(".sv-chip");
                if (!chip) return;
                document.querySelectorAll("#catChips .sv-chip").forEach(c => c.classList.remove("active"));
                chip.classList.add("active");
                activeCat = chip.dataset.cat || "";
                // Ao trocar categoria, reinicia a lista do zero.
                page = 1; done = false; loading = false;
                grid.innerHTML = "";
                loadMore();
            });
        }

        async function loadMore() {
            if (loading || done) return;
            loading = true;
            try {
                let url;
                if (type === "series") {
                    url = `/api/series?page=${page}&limit=${PAGE_SIZE}`;
                } else {
                    url = `/api/contents?type=${type}&page=${page}&limit=${PAGE_SIZE}` +
                          (activeCat ? `&category=${encodeURIComponent(activeCat)}` : "");
                }
                const res = await fetch(url);
                const data = await res.json();
                const items = type === "series" ? (data || []) : (data.items || []);

                if (!items.length) { done = true; return; }

                const frag = items.map(it =>
                    type === "live" ? liveCard(it) : type === "movie" ? movieCard(it) : seriesCard(it)
                ).join("");
                grid.insertAdjacentHTML("beforeend", frag);

                // Se veio menos que o tamanho da página, acabou.
                if (items.length < PAGE_SIZE) done = true;
                page++;
            } catch (e) {
                done = true;
            } finally {
                loading = false;
            }
        }

        const sentinel = document.createElement("div");
        sentinel.id = "svScrollSentinel";
        sentinel.style.height = "1px";
        grid.after(sentinel);

        const io = new IntersectionObserver((entries) => {
            if (entries.some(en => en.isIntersecting)) loadMore();
        }, { rootMargin: "600px" });
        io.observe(sentinel);

        // Carrega a primeira leva extra já (a inicial veio do servidor).
        loadMore();
    }

    document.addEventListener("DOMContentLoaded", () => {
        if (document.getElementById("liveGrid")) setup("live");
        else if (document.getElementById("movieGrid")) setup("movie");
        else if (document.getElementById("seriesGrid")) setup("series");
    });
})();
