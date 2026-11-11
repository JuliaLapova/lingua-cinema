"""Display audio metadata without guessing the language from the track order."""
LANGUAGES = {'en': 'Английский', 'eng': 'Английский', 'ru': 'Русский', 'rus': 'Русский',
             'fr': 'Французский', 'fra': 'Французский', 'de': 'Немецкий', 'deu': 'Немецкий',
             'es': 'Испанский', 'spa': 'Испанский', 'ja': 'Японский', 'jpn': 'Японский'}

def language_code(value):
    return value.lower().replace('_', '-').split('-')[0] if value else ''

def track_label(index, language='', title='', codec=''):
    code = language_code(language)
    name = LANGUAGES.get(code, language if code not in ('', 'und') else 'Язык не указан')
    return ' · '.join(filter(None, [f'Дорожка {index + 1} — {name}', title, codec]))

def preferred_track(tracks, saved=None, current=0):
    if isinstance(saved, int) and 0 <= saved < len(tracks):
        return saved
    return next((i for i, t in enumerate(tracks) if language_code(t[0]) in ('en', 'eng')),
                current if 0 <= current < len(tracks) else 0)
