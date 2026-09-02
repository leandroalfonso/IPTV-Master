"""Configuração do StreamVault.

Todas as configurações sensíveis vêm do .env (nunca hardcoded no código).
O .env fica na raiz do projeto (BASE_DIR).
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Diretório raiz do projeto (onde fica o app.py / .env).
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Config:
    # Expõe o diretório base também como atributo de classe.
    BASE_DIR = BASE_DIR

    SECRET_KEY = os.getenv("SECRET_KEY", "streamvault-dev-secret-change-me")

    # Tipo de provedor da lista: "m3u" (padrão) ou "xtream".
    IPTV_TYPE = os.getenv("IPTV_TYPE", "m3u").lower()

    # URL da lista M3U (http/https) OU caminho de arquivo local relativo a BASE_DIR.
    IPTV_M3U_URL = os.getenv("IPTV_M3U_URL", "")

    # Credenciais Xtream Codes (usadas apenas quando IPTV_TYPE=xtream).
    IPTV_USERNAME = os.getenv("IPTV_USERNAME", "")
    IPTV_PASSWORD = os.getenv("IPTV_PASSWORD", "")

    # Tempo de cache da lista em minutos.
    IPTV_CACHE_MINUTES = int(os.getenv("IPTV_CACHE_MINUTES", "30"))

    # Tema padrão.
    THEME = os.getenv("THEME", "dark")

    # API key do TMDB (The Movie Database) para enriquecer filmes com
    # sinopse, nota, ano, gêneros, duração e backdrop. Vazia = recurso desligado.
    TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")
    TMDB_LANGUAGE = os.getenv("TMDB_LANGUAGE", "pt-BR")

    # Caminho do banco SQLite.
    DATABASE_PATH = os.getenv(
        "DATABASE_PATH", os.path.join(BASE_DIR, "data", "streamvault.db")
    )

    DATA_DIR = os.path.join(BASE_DIR, "data")


def _reload_config() -> None:
    """Recarrega os atributos da classe Config a partir das variáveis de ambiente.

    Sem isso, save_env() escreve o .env e atualiza os.environ, mas os atributos
    de classe (lidos em importação) continuam com os valores antigos — e o
    refresh da lista usaria a URL/IPTV antiga até reiniciar o servidor.
    Chamamos isto após reescrever o .env para que a mudança surta efeito na hora.
    """
    setattr(Config, "SECRET_KEY", os.getenv("SECRET_KEY", "streamvault-dev-secret-change-me"))
    setattr(Config, "IPTV_TYPE", os.getenv("IPTV_TYPE", "m3u").lower())
    setattr(Config, "IPTV_M3U_URL", os.getenv("IPTV_M3U_URL", ""))
    setattr(Config, "IPTV_USERNAME", os.getenv("IPTV_USERNAME", ""))
    setattr(Config, "IPTV_PASSWORD", os.getenv("IPTV_PASSWORD", ""))
    setattr(Config, "IPTV_CACHE_MINUTES", int(os.getenv("IPTV_CACHE_MINUTES", "30")))
    setattr(Config, "THEME", os.getenv("THEME", "dark"))
    setattr(Config, "TMDB_API_KEY", os.getenv("TMDB_API_KEY", ""))
    setattr(Config, "TMDB_LANGUAGE", os.getenv("TMDB_LANGUAGE", "pt-BR"))


def save_env(updates: dict) -> None:
    """Persiste alterações de configuração no .env (usado pela página de Configurações).

    Atualiza a variável de ambiente em memória, reescreve o arquivo .env e
    recarrega a classe Config para que a mudança tenha efeito imediato (sem
    precisar reiniciar o servidor).
    """
    env_path = os.path.join(BASE_DIR, ".env")
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

    index = {}
    for i, line in enumerate(lines):
        if "=" in line and not line.strip().startswith("#"):
            index[line.split("=", 1)[0].strip()] = i

    for key, value in updates.items():
        if key in index:
            lines[index[key]] = f"{key}={value}"
        else:
            lines.append(f"{key}={value}")
            index[key] = len(lines) - 1

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")

    # Reflete em memória para a sessão atual e recarrega a classe Config.
    for key, value in updates.items():
        os.environ[key] = str(value)
    _reload_config()
