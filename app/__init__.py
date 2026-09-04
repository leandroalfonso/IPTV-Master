"""StreamVault - aplicação Flask de IPTV pessoal.

Pacote principal. `create_app` inicializa o banco, registra as rotas e
garante que a lista IPTV esteja carregada (ou inicia a atualização em
segundo plano) antes de servir a primeira requisição.
"""

from flask import Flask, send_from_directory

from werkzeug.middleware.proxy_fix import ProxyFix

from . import config, database, routes, proxy


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = config.Config.SECRET_KEY

    # Quando exposto atrás de um proxy reverso (nginx, Cloudflare, tunel),
    # o ProxyFix corrige scheme/host/remote-addr vindos dos cabeçalhos
    # X-Forwarded-*. Sem isso, o app pode enxergar HTTP onde o cliente usa
    # HTTPS e provocar loops de redirecionamento.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    # Garante que as tabelas existam.
    database.init_db()

    # Registra as rotas (páginas + API).
    app.register_blueprint(routes.bp)
    # Proxy de streams HLS (resolve CORS da origem IPTV).
    app.register_blueprint(proxy.bp)

    # Carrega a lista IPTV (bloqueante na primeira vez se o banco estiver
    # vazio; depois apenas agenda atualização em background quando expirado).
    routes.ensure_loaded()

    # Enriquecimento TMDB em background: filmes sem metadata ganham sinopse,
    # nota, ano e pôster real sem travar nenhuma request do usuário.
    from . import tmdb as _tmdb
    _tmdb.start_enrich_worker()

    # Favicon (evita 404 e loop em alguns proxies que re-testam o ícone).
    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(
            app.static_folder, "favicon.svg", mimetype="image/svg+xml"
        )

    return app
