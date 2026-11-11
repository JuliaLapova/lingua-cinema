import unittest
from audio_tracks import preferred_track, track_label

class AudioTracksTest(unittest.TestCase):
    def test_english_and_saved(self):
        tracks = [('ru', '', ''), ('en-US', '', '')]
        self.assertEqual(preferred_track(tracks), 1)
        self.assertEqual(preferred_track(tracks, saved=0), 0)
        self.assertEqual(preferred_track(tracks, saved=9), 1)

    def test_unlabelled_is_not_guessed(self):
        self.assertIn('Язык не указан', track_label(1, 'und'))
        self.assertEqual(preferred_track([('', '', ''), ('', '', '')], current=1), 1)

    def test_names(self):
        self.assertIn('Английский', track_label(0, 'eng', 'Original', 'MP3'))
        self.assertIn('Original', track_label(0, 'eng', 'Original', 'MP3'))
