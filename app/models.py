"""Modelo de dados de um conteúdo IPTV.

Representa um canal ao vivo, um filme ou um episódio de série de forma
normalizada, independente do formato bruto da lista (M3U ou Xtream).
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Content:
    id: str
    name: str
    type: str            # "live" | "movie" | "series"
    url: str
    logo: str = ""
    category: str = "Geral"
    group_name: str = ""
    description: str = ""
    metadata: str = "{}"
    series_name: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None

    def to_row(self, now: str):
        """Tupla na ordem exata das colunas da tabela contents."""
        return (
            self.id,
            self.name,
            self.type,
            self.url,
            self.logo,
            self.category,
            self.group_name,
            self.description,
            self.metadata,
            self.series_name,
            self.season,
            self.episode,
            now,
            now,
        )
