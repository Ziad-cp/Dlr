"""Spotify: reading embed pages and matching songs. Offline (saved embed data)."""
import unittest
from pathlib import Path

import spotify

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def entity(name):
    return spotify.parse_embed((FIXTURES / name).read_text(encoding="utf-8"))


class EmbedTest(unittest.TestCase):
    def test_track(self):
        t = spotify.track_from_entity(entity("spotify_track.json"), "4uLU6hMCjMI75M1A2tKUQC")
        self.assertEqual(t["name"], "Never Gonna Give You Up")
        self.assertEqual(t["artists"], ["Rick Astley"])
        self.assertEqual(t["year"], "1987")
        self.assertAlmostEqual(t["duration"], 213.573)
        self.assertTrue(t["cover"].endswith("/rick"))

    def test_album(self):
        c = spotify.collection_from_entity("album", entity("spotify_album.json"), "2546nbn3NfAUPMJ3X0qTJ8")
        self.assertEqual((c["name"], c["owner"]), ("Epic", "AL/SO"))
        self.assertTrue(c["cover"].endswith("/big"))  # the largest cover
        self.assertEqual([t["name"] for t in c["tracks"]], ["Epic", "House Party"])  # not the unplayable one
        self.assertEqual(c["tracks"][0]["artists"], ["AL/SO", "Impex"])
        self.assertEqual(c["tracks"][1]["number"], 2)
        self.assertEqual(c["tracks"][1]["album"], "Epic")

    def test_playlist(self):
        c = spotify.collection_from_entity("playlist", entity("spotify_playlist.json"), "37i9dQZF1DXcBWIGoYBM5M")
        self.assertEqual(c["name"], "Road Trip")
        self.assertEqual([t["name"] for t in c["tracks"]], ["Song A"])  # podcasts are left out
        self.assertEqual(c["tracks"][0]["album"], "")  # found from YouTube Music when downloading
        self.assertTrue(c["cover"].endswith("/pl"))

    def test_parse_links(self):
        self.assertEqual(spotify.parse("https://open.spotify.com/album/2546nbn3NfAUPMJ3X0qTJ8?si=x"),
                         ("album", "2546nbn3NfAUPMJ3X0qTJ8"))
        self.assertEqual(spotify.parse("open.spotify.com/intl-de/track/4uLU6hMCjMI75M1A2tKUQC"),
                         ("track", "4uLU6hMCjMI75M1A2tKUQC"))
        self.assertEqual(spotify.parse("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"),
                         ("playlist", "37i9dQZF1DXcBWIGoYBM5M"))
        with self.assertRaises(spotify.SpotifyError):
            spotify.parse("https://open.spotify.com/artist/0gxyHStUsqpMadRV0Di1Qt")
        self.assertTrue(spotify.is_collection("https://open.spotify.com/album/2546nbn3NfAUPMJ3X0qTJ8"))
        self.assertFalse(spotify.is_collection("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"))


class MatchTest(unittest.TestCase):
    track = {"name": "Never Gonna Give You Up", "artists": ["Rick Astley"], "duration": 213.5}

    def test_official_song_wins(self):
        song = {"title": "Never Gonna Give You Up", "track": "Never Gonna Give You Up",
                "artists": ["Rick Astley"], "duration": 214}
        remix = {"title": "Never Gonna Give You Up (Remix)", "channel": "DJ Someone", "duration": 215}
        self.assertGreater(spotify._score(self.track, song), spotify._score(self.track, remix))
        self.assertGreaterEqual(spotify._score(self.track, song), spotify._GOOD_ENOUGH)

    def test_wrong_length_is_rejected(self):
        long = {"title": "Never Gonna Give You Up", "artists": ["Rick Astley"], "duration": 3600}
        self.assertEqual(spotify._score(self.track, long), float("-inf"))


if __name__ == "__main__":
    unittest.main()
