/* =========================================================
   StreamVault — config.js
   Página de configurações: salvar fonte IPTV, atualizar e limpar.
   ========================================================= */
(() => {
    const form = document.getElementById('configForm');
    const msg = document.getElementById('cfgMsg');
    const btnRefresh = document.getElementById('btnRefresh');
    const btnClear = document.getElementById('btnClear');

    function showMsg(text, ok = true) {
        if (!msg) return;
        msg.innerHTML = `<div class="alert ${ok ? 'sv-alert-ok' : 'sv-alert-err'}" style="margin:0;">${text}</div>`;
    }

    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const payload = {
                IPTV_TYPE: document.getElementById('iptvType').value,
                IPTV_M3U_URL: document.getElementById('iptvUrl').value.trim(),
                IPTV_CACHE_MINUTES: document.getElementById('cacheMin').value
            };
            try {
                const res = await fetch('/api/config', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (res.ok) {
                    showMsg('Configuração salva. Clique em "Atualizar lista" para carregar os conteúdos.', true);
                } else {
                    showMsg('Erro: ' + (data.error || 'desconhecido'), false);
                }
            } catch (err) {
                showMsg('Erro de conexão ao salvar.', false);
            }
        });
    }

    if (btnRefresh) {
        btnRefresh.addEventListener('click', async () => {
            btnRefresh.disabled = true;
            const original = btnRefresh.innerHTML;
            btnRefresh.innerHTML = '<i class="bi bi-arrow-clockwise spin"></i> Atualizando...';
            try {
                const res = await fetch('/api/iptv/refresh', {method: 'POST'});
                const data = await res.json();
                if (res.ok && data.ok) {
                    showMsg(`Lista atualizada! Canais: ${data.channels} · Filmes: ${data.movies} · Séries: ${data.series}`, true);
                    // Atualiza stats na tela.
                    updateStats(data);
                } else if (res.status === 409) {
                    showMsg('Atualização já está em andamento...', true);
                } else {
                    showMsg('Falha: ' + (data.error || 'verifique a URL'), false);
                }
            } catch (err) {
                showMsg('Erro de conexão ao atualizar.', false);
            } finally {
                btnRefresh.disabled = false;
                btnRefresh.innerHTML = original;
            }
        });
    }

    if (btnClear) {
        btnClear.addEventListener('click', async () => {
            if (!confirm('Limpar todo o cache de conteúdos?')) return;
            try {
                const res = await fetch('/api/iptv/clear', {method: 'POST'});
                const data = await res.json();
                if (res.ok) { showMsg('Cache limpo.', true); updateStats({total:0,channels:0,movies:0,series:0}); }
            } catch (e) { showMsg('Erro ao limpar.', false); }
        });
    }

    function updateStats(d) {
        const map = {statTotal:'total', statLive:'channels', statMovies:'movies', statSeries:'series'};
        for (const [id, key] of Object.entries(map)) {
            const el = document.getElementById(id);
            if (el) el.textContent = d[key] ?? 0;
        }
    }
})();

/* spinner helper */
document.addEventListener('DOMContentLoaded', () => {
    const style = document.createElement('style');
    style.textContent = '.spin{animation:svspin 1s linear infinite}@keyframes svspin{to{transform:rotate(360deg)}}.sv-alert-ok{background:rgba(40,167,69,.15);border:1px solid #28a745;color:#aef5c0;padding:10px 14px;border-radius:8px}.sv-alert-err{background:rgba(229,9,20,.12);border:1px solid var(--accent);color:#ffb3b8;padding:10px 14px;border-radius:8px}';
    document.head.appendChild(style);
});
