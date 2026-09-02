/* =========================================================
   StreamVault — app.js
   Interações gerais: header, carrosséis, favoritos, pesquisa, toasts.
   Fetch API puro (sem jQuery/React/Vue).
   ========================================================= */
const SV = (() => {
    const toastEl = document.getElementById('svToast');
    const toastBody = document.getElementById('svToastBody');
    let toastInstance = null;

    function toast(msg) {
        if (!toastEl) return;
        toastBody.textContent = msg;
        if (!toastInstance) toastInstance = new bootstrap.Toast(toastEl, {delay: 2600});
        toastInstance.show();
    }

    /* -------- Header: fundo blur ao rolar -------- */
    const navbar = document.getElementById('svNavbar');
    if (navbar) {
        const onScroll = () => {
            if (window.scrollY > 40) navbar.classList.add('scrolled');
            else navbar.classList.remove('scrolled');
        };
        window.addEventListener('scroll', onScroll, {passive: true});
        onScroll();
    }

    /* -------- Carrosséis: setas prev/next -------- */
    function initCarousels() {
        document.querySelectorAll('.sv-carousel').forEach(car => {
            const row = car.querySelector('.sv-row');
            const prev = car.querySelector('.sv-carousel-btn.prev');
            const next = car.querySelector('.sv-carousel-btn.next');
            if (!row) return;
            const step = () => Math.max(row.clientWidth * 0.8, 240);
            if (prev) prev.addEventListener('click', () => row.scrollBy({left: -step(), behavior: 'smooth'}));
            if (next) next.addEventListener('click', () => row.scrollBy({left: step(), behavior: 'smooth'}));
        });
    }
    initCarousels();

    /* -------- Tema e perfil -------- */
    const savedTheme = localStorage.getItem('sv-theme') || 'dark';
    const applyTheme = (theme) => {
        const root = document.documentElement;
        const isDark = theme === 'dark';
        root.setAttribute('data-theme', theme);
        document.body.classList.toggle('sv-light-theme', !isDark);
        const toggle = document.querySelector('.sv-theme-toggle i');
        if (toggle) toggle.className = isDark ? 'bi bi-sun-fill' : 'bi bi-moon-stars-fill';
    };

    const themeToggle = document.querySelector('.sv-theme-toggle');
    if (themeToggle) {
        applyTheme(savedTheme);
        themeToggle.addEventListener('click', () => {
            const nextTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            localStorage.setItem('sv-theme', nextTheme);
            applyTheme(nextTheme);
            toast(nextTheme === 'dark' ? 'Tema escuro ativado' : 'Tema claro ativado');
        });
    }

    const profileBtn = document.querySelector('.sv-profile-btn');
    if (profileBtn) {
        profileBtn.addEventListener('click', () => {
            const profileLabel = localStorage.getItem('sv-profile') || 'Usuário';
            const nextLabel = profileLabel === 'Usuário' ? 'Família' : 'Usuário';
            localStorage.setItem('sv-profile', nextLabel);
            profileBtn.title = nextLabel;
            profileBtn.setAttribute('aria-label', `Perfil ${nextLabel}`);
            toast(`Perfil ativo: ${nextLabel}`);
        });
    }

    /* -------- Cinema mode -------- */
    const cinemaToggle = document.querySelector('.sv-cinema-toggle');
    if (cinemaToggle) {
        const applyCinemaMode = (enabled) => {
            document.body.classList.toggle('sv-cinema-mode', enabled);
            const icon = cinemaToggle.querySelector('i');
            if (icon) icon.className = enabled ? 'bi bi-broadcast' : 'bi bi-aspect-ratio';
            cinemaToggle.title = enabled ? 'Sair do modo cinema' : 'Modo cinema';
        };

        const savedCinema = localStorage.getItem('sv-cinema-mode') === 'true';
        applyCinemaMode(savedCinema);
        cinemaToggle.addEventListener('click', () => {
            const enabled = !document.body.classList.contains('sv-cinema-mode');
            localStorage.setItem('sv-cinema-mode', String(enabled));
            applyCinemaMode(enabled);
            toast(enabled ? 'Modo cinema ativado' : 'Modo cinema desativado');
        });
    }

    /* -------- Favoritos -------- */
    async function toggleFavorite(btn) {
        const id = btn.dataset.id;
        if (!id) return;
        const isRemove = btn.classList.contains('sv-fav-remove');
        if (isRemove) return;

        try {
            const res = await fetch('/api/favorites', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    content_id: id,
                    content_type: btn.dataset.type || '',
                    name: btn.dataset.name || '',
                    logo: btn.dataset.logo || '',
                    url: btn.dataset.url || ''
                })
            });
            if (res.ok) {
                btn.innerHTML = '<i class="bi bi-check2"></i> <span>Na minha lista</span>';
                btn.classList.add('is-fav');
                toast('✓ Adicionado à Minha Lista');
            } else {
                toast('Não foi possível adicionar.');
            }
        } catch (e) {
            toast('Erro de conexão.');
        }
    }

    document.addEventListener('click', (e) => {
        const favBtn = e.target.closest('.sv-fav');
        if (favBtn) { e.preventDefault(); toggleFavorite(favBtn); }
    });

    /* -------- Pesquisa dinâmica (debounce) -------- */
    const searchInput = document.getElementById('svSearch');
    const resultsBox = document.getElementById('svSearchResults');

    function resItem(item, href) {
        const img = item.logo
            ? `<img src="/proxy/image?u=${encodeURIComponent(item.logo)}" alt="" loading="lazy" onerror="this.outerHTML='<div class=\\'sv-res-noimg\\'><i class=\\'bi bi-play-circle\\'></i></div>'">`
            : '<div class="sv-res-noimg"><i class="bi bi-play-circle"></i></div>';
        const sub = item.category || item.group_name || '';
        return `<a class="sv-res-item" href="${href}">${img}<div><div class="sv-res-name">${escapeHtml(item.name)}</div><small class="sv-res-sub">${escapeHtml(sub)}</small></div></a>`;
    }

    function renderResults(data) {
        if (!resultsBox) return;
        let html = '';
        const hasAny = (data.channels.length + data.movies.length + data.series.length) > 0;
        if (!hasAny) {
            html = '<p class="text-secondary px-2">Nenhum resultado encontrado.</p>';
        } else {
            if (data.channels.length) {
                html += '<h6>Canais</h6>';
                data.channels.forEach(c => html += resItem(c, '/assistir/'+c.id));
            }
            if (data.movies.length) {
                html += '<h6>Filmes</h6>';
                data.movies.forEach(m => html += resItem(m, '/detalhes/'+m.id));
            }
            if (data.series.length) {
                html += '<h6>Séries</h6>';
                data.series.forEach(s => html += resItem(
                    {name: s.series_name, logo: s.logo, category: 'Série'},
                    '/detalhes-series/'+encodeURIComponent(s.series_name)));
            }
        }
        resultsBox.innerHTML = html;
        resultsBox.classList.remove('d-none');
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }

    let searchTimer;
    if (searchInput) {
        searchInput.addEventListener('input', () => {
            clearTimeout(searchTimer);
            const q = searchInput.value.trim();
            if (q.length < 1) { resultsBox.classList.add('d-none'); return; }
            searchTimer = setTimeout(async () => {
                try {
                    const res = await fetch('/api/search?q=' + encodeURIComponent(q));
                    const data = await res.json();
                    renderResults(data);
                } catch (e) { /* silencioso */ }
            }, 250);
        });
        document.addEventListener('click', (e) => {
            if (resultsBox && !resultsBox.contains(e.target) && e.target !== searchInput) {
                resultsBox.classList.add('d-none');
            }
        });
        // fecha com Esc
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') resultsBox.classList.add('d-none');
        });
    }

    return { toast };
})();

window.SV = SV;
