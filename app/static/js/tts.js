// Botão "Ouvir descrição" — voz via Edge TTS no servidor (proxy), com
// fallback para a Web Speech API do próprio dispositivo se a Microsoft
// estiver fora do ar ou o idioma não tiver voz neural conhecida.
(function () {
    'use strict';

    var player = new Audio();
    var currentBtn = null;   // botão em reprodução/preparação
    var mode = null;         // 'edge' | 'browser' | 'loading'

    function setUI(btn, ic, lb) {
        var i = btn.querySelector('i');
        if (i) i.className = ic;
        var l = btn.querySelector('.sv-tts-label');
        if (l) l.textContent = lb;
    }

    function stopPlayback() {
        try { player.pause(); } catch (e) {}
        player.removeAttribute('src');
        player.load();
        if (window.speechSynthesis) window.speechSynthesis.cancel();
        if (currentBtn) { setUI(currentBtn, 'bi bi-volume-up-fill', 'Ouvir descrição'); }
        currentBtn = null;
        mode = null;
    }

    function finish() {
        if (currentBtn) { setUI(currentBtn, 'bi bi-volume-up-fill', 'Ouvir descrição'); }
        currentBtn = null;
        mode = null;
    }

    // Fallback local: vozes pt-BR nativas do SO/browser.
    function browserSpeak(text, btn) {
        if (!('speechSynthesis' in window)) { finish(); return; }
        window.speechSynthesis.cancel();
        var u = new SpeechSynthesisUtterance(text);
        var lang = (navigator.language || 'pt-BR').toLowerCase();
        u.lang = lang.indexOf('pt') === 0 ? 'pt-BR' : lang;
        var voices = window.speechSynthesis.getVoices() || [];
        var match = voices.filter(function (v) {
            return (v.lang || '').toLowerCase().indexOf(lang.split('-')[0]) === 0;
        })[0];
        if (match) u.voice = match;
        u.onend = finish;
        u.onerror = finish;
        mode = 'browser';
        setUI(btn, 'bi bi-stop-circle', 'Parar');
        window.speechSynthesis.speak(u);
    }

    function describe(btn) {
        var desc = document.getElementById('sv-desc-text');
        var text = desc ? desc.textContent.trim() : '';
        if (!text) { return; }

        // clicar no botão ativo = parar
        if (currentBtn === btn) { stopPlayback(); return; }
        if (currentBtn) { stopPlayback(); }

        currentBtn = btn;
        mode = 'loading';
        setUI(btn, 'bi bi-arrow-repeat', 'Preparando voz…');

        fetch('/tts?id=' + encodeURIComponent(btn.dataset.id) +
              '&lang=' + encodeURIComponent(navigator.language || 'pt-BR'))
            .then(function (resp) {
                if (resp.ok) { return resp.blob(); }
                return resp.json().catch(function () { return {}; });
            })
            .then(function (r) {
                if (currentBtn !== btn) { return; } // usuário parou/trocou
                if (r instanceof Blob && r.size > 0) {
                    mode = 'edge';
                    setUI(btn, 'bi bi-stop-circle', 'Parar');
                    player.src = URL.createObjectURL(r);
                    player.onended = finish;
                    player.onerror = function () { browserSpeak(text, btn); };
                    player.play().catch(function () { browserSpeak(text, btn); });
                } else {
                    browserSpeak(text, btn); // servidor indicou fallback
                }
            })
            .catch(function () {
                if (currentBtn === btn) { browserSpeak(text, btn); }
            });
    }

    document.addEventListener('click', function (e) {
        var btn = e.target.closest('.sv-tts-btn');
        if (btn) { describe(btn); }
    });
})();
