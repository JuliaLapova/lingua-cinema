import unittest
from subtitles import Cue, parse, align

class SubtitlesTest(unittest.TestCase):
    def test_srt(self):
        self.assertEqual(parse('\ufeff1\r\n00:00:01,000 --> 00:00:03,500\r\n<i>Hello</i> &amp; goodbye\r\n'), [Cue(1, 3.5, 'Hello & goodbye')])

    def test_vtt(self):
        self.assertEqual(parse('WEBVTT\n\nNOTE ignored\n\nabc\n00:01.250 --> 00:04.000 align:start\n<v Speaker>Hello\nthere</v>'), [Cue(1.25, 4, 'Hello\nthere')])

    def test_alignment_not_index(self):
        en = [Cue(1, 3, 'One'), Cue(5, 9, 'Two')]
        ru = [Cue(5, 6, 'Два'), Cue(6, 9, 'продолжение'), Cue(20, 21, 'Отдельно')]
        self.assertEqual(align(en, ru), [(en[0], ''), (en[1], 'Два\nпродолжение'), (Cue(20, 21, ''), 'Отдельно')])

    def test_invalid(self):
        self.assertEqual(parse('1\n00:02.000 --> 00:01.000\nInvalid'), [])

if __name__ == '__main__':
    unittest.main()
