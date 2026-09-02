"""Ponto de entrada da aplicação StreamVault.

Uso:
    python app.py
A aplicação sobe em http://0.0.0.0:5000 (acessível na rede local, necessário
para o Google Cast/Chromecast alcançar o servidor pela TV). Para restringir ao
loopback, defina HOST=127.0.0.1.

Servidor: Waitress (WSGI de produção). O dev server do Werkzeug não suporta
streams longos/concorrentes — derrubava as conexões durante a reprodução e o
Cast. Waitress lida com range requests, streams longos e múltiplos clientes.
"""

import os

from app import create_app

app = create_app()


if __name__ == "__main__":
    host = os.getenv("HOST") or "0.0.0.0"
    port = int(os.getenv("PORT", "5000"))
    threads = int(os.getenv("THREADS", "16"))

    if os.getenv("FLASK_DEBUG", "0") == "1":
        # Modo desenvolvimento: mantém o reloader do Werkzeug.
        app.run(host=host, port=port, debug=True, threaded=True)
    else:
        from waitress import serve

        serve(
            app,
            host=host,
            port=port,
            threads=threads,
            # Conexões de streaming (mídia) podem ficar abertas por muito tempo;
            # canal_timeout alto evita que o servidor derrube streams longos.
            channel_timeout=3600,
            # Não limitar o tamanho de body de resposta; stream direto.
            max_request_body_size=1073741824,
        )
