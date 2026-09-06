import unittest

from app.iptv import summarize_m3u_text


class IPTVValidationTests(unittest.TestCase):
    def test_summarize_m3u_text_counts_valid_entries_without_persisting(self):
        text = '''#EXTM3U
#EXTINF:-1 group-title="Canais",News
https://example.test/news.m3u8
#EXTINF:-1 group-title="Filmes",Movie
https://example.test/movie.mp4
#EXTINF:-1 group-title="Series",Show S01E01
https://example.test/show.mp4
'''
        self.assertEqual(summarize_m3u_text(text), {
            "total": 3,
            "channels": 1,
            "movies": 1,
            "series": 1,
        })

    def test_summarize_m3u_text_rejects_empty_or_invalid_playlist(self):
        with self.assertRaisesRegex(ValueError, "nenhuma entrada"):
            summarize_m3u_text("#EXTM3U\n")


if __name__ == '__main__':
    unittest.main()
