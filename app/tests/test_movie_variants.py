import unittest

from app.database import group_movie_variants


class MovieVariantGroupingTests(unittest.TestCase):
    def test_same_movie_dubbed_and_subtitled_becomes_one_item_with_two_variants(self):
        rows = [
            {
                "id": "dub-id",
                "name": "O Exemplo (Dublado)",
                "type": "movie",
                "url": "https://media.example/dub.mp4",
                "logo": "poster.jpg",
                "category": "Filmes",
                "group_name": "Filmes",
            },
            {
                "id": "sub-id",
                "name": "O Exemplo (Legendado)",
                "type": "movie",
                "url": "https://media.example/sub.mp4",
                "logo": "poster.jpg",
                "category": "Filmes",
                "group_name": "Filmes",
            },
        ]

        grouped = group_movie_variants(rows)

        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]["name"], "O Exemplo")
        self.assertEqual(
            [(variant["label"], variant["id"]) for variant in grouped[0]["variants"]],
            [("Dublado", "dub-id"), ("Legendado", "sub-id")],
        )

    def test_different_movies_with_similar_titles_are_not_grouped(self):
        rows = [
            {
                "id": "one",
                "name": "O Exemplo (Dublado)",
                "type": "movie",
                "url": "https://media.example/one.mp4",
                "category": "Filmes",
            },
            {
                "id": "two",
                "name": "O Exemplo 2 (Legendado)",
                "type": "movie",
                "url": "https://media.example/two.mp4",
                "category": "Filmes",
            },
        ]

        grouped = group_movie_variants(rows)

        self.assertEqual(len(grouped), 2)
        self.assertEqual({item["name"] for item in grouped}, {"O Exemplo", "O Exemplo 2"})

    def test_movie_without_language_marker_keeps_one_default_variant(self):
        rows = [
            {
                "id": "plain",
                "name": "Filme Sem Marcador",
                "type": "movie",
                "url": "https://media.example/plain.mp4",
                "category": "Filmes",
            }
        ]

        grouped = group_movie_variants(rows)

        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]["variants"][0]["label"], "Assistir")
        self.assertEqual(grouped[0]["variants"][0]["id"], "plain")


if __name__ == "__main__":
    unittest.main()
