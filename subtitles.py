"""Subtitle parsing and time-based bilingual alignment (no external dependencies)."""
from dataclasses import dataclass
import html
import re

@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str

TIME = r'(?:\d+:)?\d{2}:\d{2}[.,]\d{3}'

def seconds(value):
    parts = value.replace(',', '.').split(':')
    return sum(float(p) * 60 ** i for i, p in enumerate(reversed(parts)))

def parse(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n').lstrip('\ufeff')
    cues = []
    for block in re.split(r'\n\s*\n', text):
        if block.lstrip().startswith(('NOTE', 'STYLE', 'REGION')):
            continue
        match = re.search(rf'({TIME})\s*-->\s*({TIME})[^\n]*\n(.*)', block, re.S)
        if not match:
            continue
        start, end = seconds(match[1]), seconds(match[2])
        body = html.unescape(re.sub(r'<[^>]+>', '', match[3])).strip()
        body = re.sub(r'\{\\[^}]*\}', '', body)
        if body and end > start:
            cues.append(Cue(start, end, body))
    return sorted(cues, key=lambda c: (c.start, c.end))

def read(path):
    data = path.read_bytes()
    for encoding in ('utf-8-sig', 'utf-16' if data[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8', 'cp1251'):
        try:
            return parse(data.decode(encoding))
        except UnicodeError:
            pass
    return []

def align(english, russian):
    """Keep all cues; attach Russian by greatest temporal overlap, never row number."""
    if not english:
        return [(c, '') for c in russian]
    attached = [[] for _ in english]
    extra = []
    for ru in russian:
        overlaps = [max(0, min(en.end, ru.end) - max(en.start, ru.start)) for en in english]
        best = max(overlaps, default=0)
        if best:
            attached[overlaps.index(best)].append(ru.text)
        else:
            extra.append((Cue(ru.start, ru.end, ''), ru.text))
    return sorted([(c, '\n'.join(attached[i])) for i, c in enumerate(english)] + extra, key=lambda row: row[0].start)

def timestamp(t):
    t = max(0, int(t))
    return f'{t // 3600}:{t // 60 % 60:02}:{t % 60:02}' if t >= 3600 else f'{t // 60:02}:{t % 60:02}'
