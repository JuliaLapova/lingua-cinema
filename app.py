#!/usr/bin/env python3
"""Lingua Cinema — local Linux video player with bilingual transcript."""
import json
import os
from pathlib import Path
import subprocess
import threading
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gst', '1.0')
from gi.repository import Gtk, Gst, GLib, Gdk
from subtitles import parse, read, align, timestamp

Gst.init(None)

CSS = b'''
window { background: #101217; color: #eceef5; }
headerbar { background: #191c24; border-bottom: 1px solid #303442; }
button { background: #272c38; color: #eef1f8; border: 1px solid #3b4253; border-radius: 8px; padding: 7px 11px; }
button:hover { background: #39435b; }
label { color: #e4e8f2; }
list, scrolledwindow { background: #171a22; }
row { padding: 14px; border-bottom: 1px solid #292e3c; }
row.active { background: #263552; border-left: 4px solid #85abff; }
.english { font-size: 17px; }
.russian { color: #aebbd1; font-size: 15px; }
.muted { color: #97a3b9; font-size: 12px; }
.title { font-size: 21px; font-weight: bold; }
scale trough { background: #343b4c; }
scale highlight { background: #86aaff; }
'''

class Player(Gtk.Window):
    def __init__(self):
        super().__init__(title='Lingua Cinema')
        self.set_default_size(1240, 780)
        self.set_size_request(820, 540)
        self.connect('destroy', self.close)
        self.path = None
        self.english, self.russian, self.rows, self.data = [], [], [], []
        self.generation = 0
        self.playing = False
        self.dragging = False
        self.duration = 0
        self.rate = 1.0
        self.current = -1
        self.subtitle_offset = 0.0
        self.track_indices = []
        self.state_path = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'lingua-cinema/history.json'
        try:
            self.history = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            self.history = {}
        self.pipeline = Gst.ElementFactory.make('playbin', 'player')
        sink = Gst.ElementFactory.make('gtksink', 'video')
        if not self.pipeline or not sink:
            raise RuntimeError('Нужны GStreamer playbin и gtksink. См. README.md.')
        self.pipeline.set_property('video-sink', sink)
        # Subtitles are rendered in our transcript rather than over the video.
        self.pipeline.set_property('flags', int(self.pipeline.get_property('flags')) & ~4)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect('message', self.message)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        header = Gtk.HeaderBar(title='Lingua Cinema', subtitle='Смотрите. Слушайте. Понимайте.')
        header.set_show_close_button(True)
        header.pack_start(self.button('Открыть фильм', self.choose_video))
        self.set_titlebar(header)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)
        split = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        split.set_position(790)
        root.pack_start(split, True, True, 0)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        left.set_border_width(16)
        split.pack1(left, True, False)
        self.title_label = Gtk.Label(label='Ваш кинотеатр для английского', xalign=0)
        self.title_label.get_style_context().add_class('title')
        left.pack_start(self.title_label, False, False, 0)
        self.video_widget = sink.get_property('widget')
        left.pack_start(self.video_widget, True, True, 0)
        self.progress = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 0.1)
        self.progress.set_draw_value(False)
        self.progress.connect('button-press-event', self.begin_drag)
        self.progress.connect('button-release-event', self.end_drag)
        self.progress.connect('change-value', self.change_progress)
        left.pack_start(self.progress, False, False, 0)
        controls = Gtk.Box(spacing=8)
        self.play_button = self.button('▶', self.toggle)
        for button in [self.button('−5 с', lambda *_: self.seek(self.position()-5)), self.play_button, self.button('+5 с', lambda *_: self.seek(self.position()+5)), self.button('↺ Реплика', self.repeat)]:
            controls.pack_start(button, False, False, 0)
        self.clock = Gtk.Label(label='00:00 / 00:00')
        controls.pack_start(self.clock, True, True, 0)
        speed = Gtk.ComboBoxText()
        self.speed_combo = speed
        for value in ['0.75', '0.9', '1.0', '1.25', '1.5']:
            speed.append_text(value + '×')
        speed.set_active(2)
        speed.connect('changed', self.speed_changed)
        controls.pack_start(speed, False, False, 0)
        volume = Gtk.VolumeButton()
        volume.set_value(0.8)
        self.pipeline.set_property('volume', 0.8)
        volume.connect('value-changed', lambda _, value: self.pipeline.set_property('volume', value))
        controls.pack_start(volume, False, False, 0)
        left.pack_start(controls, False, False, 0)
        self.audio = Gtk.ComboBoxText()
        self.audio.set_tooltip_text('Выберите английскую звуковую дорожку')
        self.audio.connect('changed', self.audio_changed)
        left.pack_start(self.audio, False, False, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        right.set_size_request(330, -1)
        right.set_border_width(12)
        split.pack2(right, False, False)
        label = Gtk.Label(label='Диалоги · EN + RU', xalign=0)
        label.get_style_context().add_class('title')
        right.pack_start(label, False, False, 0)
        load = Gtk.Box(spacing=8)
        load.pack_start(self.button('EN · Загрузить', lambda *_: self.choose_sub('en')), True, True, 0)
        load.pack_start(self.button('RU · Загрузить', lambda *_: self.choose_sub('ru')), True, True, 0)
        right.pack_start(load, False, False, 0)
        self.follow = Gtk.CheckButton(label='Следовать за текущей репликой')
        self.follow.set_active(True)
        right.pack_start(self.follow, False, False, 0)
        offset_box = Gtk.Box(spacing=8)
        offset_box.pack_start(Gtk.Label(label='Сдвиг субтитров, с'), False, False, 0)
        offset = Gtk.SpinButton.new_with_range(-600, 600, 0.1)
        offset.set_digits(1)
        offset.connect('value-changed', self.offset_changed)
        self.offset = offset
        offset_box.pack_start(offset, True, True, 0)
        right.pack_start(offset_box, False, False, 0)
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.connect('row-activated', self.row_clicked)
        self.scroller.add(self.listbox)
        right.pack_start(self.scroller, True, True, 0)
        self.status = Gtk.Label(label='Откройте фильм. Субтитры можно загрузить из файлов SRT или VTT.', xalign=0)
        self.status.set_line_wrap(True)
        self.status.set_margin_start(16)
        self.status.set_margin_end(16)
        self.status.set_margin_top(10)
        self.status.set_margin_bottom(10)
        root.pack_start(self.status, False, False, 0)
        self.connect('key-press-event', self.key)
        self.rebuild()
        GLib.timeout_add(150, self.tick)

    def button(self, label, callback):
        button = Gtk.Button(label=label)
        button.connect('clicked', callback)
        return button

    def select_file(self, title, patterns):
        dialog = Gtk.FileChooserDialog(title=title, transient_for=self, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons('Отмена', Gtk.ResponseType.CANCEL, 'Открыть', Gtk.ResponseType.OK)
        filt = Gtk.FileFilter()
        filt.set_name(title)
        for pattern in patterns:
            filt.add_pattern(pattern)
        dialog.add_filter(filt)
        all_files = Gtk.FileFilter()
        all_files.set_name('Все файлы')
        all_files.add_pattern('*')
        dialog.add_filter(all_files)
        path = dialog.get_filename() if dialog.run() == Gtk.ResponseType.OK else None
        dialog.destroy()
        return Path(path) if path else None

    def choose_video(self, *_):
        path = self.select_file('Выберите фильм', ['*.mkv', '*.mp4', '*.avi', '*.webm', '*.mov', '*.m4v'])
        if path:
            self.open_video(path)

    def open_video(self, path):
        self.save()
        self.pipeline.set_state(Gst.State.NULL)
        self.generation += 1
        self.path = path.resolve()
        self.english, self.russian = [], []
        self.audio.remove_all()
        saved = self.history.get(str(self.path), {})
        self.resume = saved.get('position', 0)
        self.offset.set_value(saved.get('offset', 0))
        self.rate = 1.0
        self.speed_combo.set_active(2)
        self.duration = 0
        self.progress.set_range(0, 1)
        self.title_label.set_text(self.path.name)
        self.pipeline.set_property('uri', self.path.as_uri())
        self.pipeline.set_state(Gst.State.PAUSED)
        self.playing = False
        self.play_button.set_label('▶')
        self.status.set_text('Ищу субтитры и звуковые дорожки…')
        self.rebuild()
        threading.Thread(target=self.inspect, args=(self.path, self.generation, saved), daemon=True).start()

    def inspect(self, path, generation, saved):
        found = {}
        for lang in ('en', 'ru'):
            previous = saved.get(lang)
            if previous and Path(previous).is_file():
                try:
                    found[lang] = (read(Path(previous)), previous)
                except OSError:
                    pass
            if lang not in found:
                for suffix in (lang, 'eng' if lang == 'en' else 'rus'):
                    for ext in ('srt', 'vtt'):
                        candidate = path.with_name(f'{path.stem}.{suffix}.{ext}')
                        if candidate.exists():
                            found[lang] = (read(candidate), str(candidate))
                            break
        streams = []
        try:
            result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(path)], capture_output=True, text=True, timeout=30, check=True)
            streams = json.loads(result.stdout).get('streams', [])
            for stream in streams:
                if stream.get('codec_type') != 'subtitle':
                    continue
                tag = stream.get('tags', {}).get('language', '').lower()
                lang = {'eng': 'en', 'en': 'en', 'rus': 'ru', 'ru': 'ru'}.get(tag)
                if not lang or lang in found:
                    continue
                # Text tracks only: image subtitle formats cannot be converted to SRT.
                if stream.get('codec_name') not in ('subrip', 'ass', 'ssa', 'webvtt', 'mov_text', 'text'):
                    continue
                sub = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', f"0:{stream['index']}", '-f', 'srt', '-'], capture_output=True, text=True, timeout=120, check=True)
                found[lang] = (parse(sub.stdout), None)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        GLib.idle_add(self.inspected, generation, found, streams)

    def inspected(self, generation, found, streams):
        if generation != self.generation:
            return False
        for lang, (cues, source) in found.items():
            # Do not overwrite a subtitle file chosen while inspection was running.
            if not getattr(self, 'english' if lang == 'en' else 'russian'):
                setattr(self, 'english' if lang == 'en' else 'russian', cues)
                if source:
                    self.history.setdefault(str(self.path), {})[lang] = source
        english_track = -1
        for i, stream in enumerate(s for s in streams if s.get('codec_type') == 'audio'):
            tags = stream.get('tags', {})
            language = tags.get('language', 'язык не указан')
            self.audio.append_text(f'Звук {i + 1}: {language} · {tags.get("title", stream.get("codec_name", ""))}')
            if language in ('en', 'eng'):
                english_track = i
        if self.audio.get_model() and len(self.audio.get_model()):
            self.audio.set_active(english_track if english_track >= 0 else 0)
        self.rebuild()
        self.subtitle_status()
        return False

    def choose_sub(self, lang):
        path = self.select_file('Английские субтитры' if lang == 'en' else 'Русские субтитры', ['*.srt', '*.vtt'])
        if not path:
            return
        try:
            cues = read(path)
            if not cues:
                raise ValueError('Не удалось найти реплики. Выберите текстовый файл SRT или VTT.')
        except (OSError, ValueError) as error:
            self.status.set_text(str(error))
            return
        setattr(self, 'english' if lang == 'en' else 'russian', cues)
        if self.path:
            self.history.setdefault(str(self.path), {})[lang] = str(path)
        self.rebuild()
        self.subtitle_status()

    def subtitle_status(self):
        missing = []
        if not self.english:
            missing.append('английские')
        if not self.russian:
            missing.append('русские')
        self.status.set_text(('Загрузите ' + ' и '.join(missing) + ' субтитры кнопками EN / RU. Автоматический перевод пока не подключён.') if missing else f'Готово · EN: {len(self.english)} реплик · RU: {len(self.russian)} реплик. Нажмите реплику, чтобы перейти к ней.')

    def rebuild(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        self.rows = []
        self.current = -1
        self.data = align(self.english, self.russian)
        if not self.data:
            label = Gtk.Label(label='Здесь появятся диалоги\n\nАнглийская реплика\nи русский перевод под ней.\n\nЗагрузите EN и RU субтитры\nили откройте фильм с ними.')
            label.set_margin_top(70)
            label.set_margin_bottom(70)
            self.listbox.add(label)
        for cue, translation in self.data:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            for text, css in [(timestamp(cue.start), 'muted'), (cue.text, 'english' if self.english else 'russian'), (translation, 'russian')]:
                if not text:
                    continue
                label = Gtk.Label(label=text, xalign=0)
                label.set_line_wrap(True)
                label.set_max_width_chars(45)
                label.get_style_context().add_class(css)
                box.pack_start(label, False, False, 0)
            row.add(box)
            self.listbox.add(row)
            self.rows.append(row)
        self.listbox.show_all()

    def row_clicked(self, _, row):
        index = row.get_index()
        if 0 <= index < len(self.data):
            self.seek(self.data[index][0].start + self.subtitle_offset)
            self.set_playing(True)

    def position(self):
        ok, value = self.pipeline.query_position(Gst.Format.TIME)
        return value / Gst.SECOND if ok else 0

    def seek(self, value):
        if not self.path:
            return
        value = max(0, min(value, self.duration or value))
        self.pipeline.seek(self.rate, Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE, Gst.SeekType.SET, int(value * Gst.SECOND), Gst.SeekType.NONE, 0)

    def set_playing(self, playing):
        if self.path:
            self.playing = playing
            self.pipeline.set_state(Gst.State.PLAYING if playing else Gst.State.PAUSED)
            self.play_button.set_label('❚❚' if playing else '▶')

    def toggle(self, *_):
        self.set_playing(not self.playing)

    def repeat(self, *_):
        if self.current >= 0:
            self.seek(self.data[self.current][0].start + self.subtitle_offset)
            self.set_playing(True)

    def speed_changed(self, combo):
        self.rate = float(combo.get_active_text().rstrip('×'))
        self.seek(self.position())

    def offset_changed(self, spin):
        self.subtitle_offset = spin.get_value()

    def audio_changed(self, combo):
        if combo.get_active() >= 0:
            self.pipeline.set_property('current-audio', combo.get_active())

    def begin_drag(self, *_):
        self.dragging = True
        return False

    def end_drag(self, *_):
        self.seek(self.progress.get_value())
        self.dragging = False
        return False

    def change_progress(self, _, scroll, value):
        if not self.dragging:
            self.seek(value)
        return False

    def tick(self):
        if self.path:
            ok, duration = self.pipeline.query_duration(Gst.Format.TIME)
            if ok and duration > 0:
                self.duration = duration / Gst.SECOND
                self.progress.set_range(0, self.duration)
            pos = self.position()
            if not self.dragging:
                self.progress.set_value(pos)
            self.clock.set_text(f'{timestamp(pos)} / {timestamp(self.duration)}')
            subtime = pos - self.subtitle_offset
            active = next((i for i, (cue, _) in enumerate(self.data) if cue.start <= subtime < cue.end), -1)
            if active != self.current:
                if self.current >= 0:
                    self.rows[self.current].get_style_context().remove_class('active')
                self.current = active
                if active >= 0:
                    row = self.rows[active]
                    row.get_style_context().add_class('active')
                    if self.follow.get_active():
                        adjustment = self.scroller.get_vadjustment()
                        adjustment.set_value(max(0, min(row.get_allocation().y - 60, adjustment.get_upper() - adjustment.get_page_size())))
        return True

    def message(self, _, message):
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            self.set_playing(False)
            self.status.set_text('Не удалось воспроизвести файл: ' + error.message)
        elif message.type == Gst.MessageType.EOS:
            self.set_playing(False)
            self.seek(0)
        elif message.type == Gst.MessageType.ASYNC_DONE and getattr(self, 'resume', 0):
            value, self.resume = self.resume, 0
            self.seek(value)

    def key(self, _, event):
        if isinstance(self.get_focus(), (Gtk.Entry, Gtk.SpinButton)):
            return False
        if event.keyval == Gdk.KEY_space:
            self.toggle()
        elif event.keyval in (Gdk.KEY_Left, Gdk.KEY_Right):
            self.seek(self.position() + (-5 if event.keyval == Gdk.KEY_Left else 5))
        else:
            return False
        return True

    def save(self):
        if not self.path:
            return
        self.history.setdefault(str(self.path), {}).update(position=self.position(), offset=self.subtitle_offset)
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.history, ensure_ascii=False), encoding='utf-8')
            temporary.replace(self.state_path)
        except OSError:
            pass

    def close(self, *_):
        self.save()
        self.pipeline.set_state(Gst.State.NULL)
        Gtk.main_quit()

if __name__ == '__main__':
    import sys
    window = Player()
    window.show_all()
    if len(sys.argv) > 1:
        window.open_video(Path(sys.argv[1]))
    Gtk.main()
