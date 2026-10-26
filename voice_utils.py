"""Numpy-only audio/text helpers for voice cloning.

Everything here works on mono float32 arrays so it can be unit-tested without
loading any model: reference passage selection, reference quality analysis,
output post-processing, crossfade stitching and Portuguese-aware text chunking.
"""
import re

import numpy as np

SILENCE_FLOOR_DB = -50.0   # below this a frame is treated as silence
FRAME_MS = 20


def to_mono(x):
    """Returns a 1-D float32 array from (n,) or (n, channels) audio."""
    x = np.asarray(x, dtype=np.float32)
    if x.ndim > 1:
        x = x.mean(axis=1)
    return x


def _db_to_amp(db):
    return 10.0 ** (db / 20.0)


def frame_db(x, sr, frame_ms=FRAME_MS):
    """Returns (per-frame RMS level in dBFS, samples per frame)."""
    n = max(1, int(sr * frame_ms / 1000))
    frames = len(x) // n
    if frames == 0:
        return np.array([-120.0], dtype=np.float32), n
    chunks = x[:frames * n].reshape(frames, n)
    rms = np.sqrt(np.mean(chunks ** 2, axis=1))
    return (20.0 * np.log10(rms + 1e-10)).astype(np.float32), n


def _close_short_gaps(mask, max_gap_frames):
    """Marks non-speech runs shorter than max_gap_frames (between speech) as speech."""
    mask = mask.copy()
    idx = np.flatnonzero(mask)
    if idx.size < 2:
        return mask
    gaps = np.diff(idx)
    for pos in np.flatnonzero((gaps > 1) & (gaps - 1 <= max_gap_frames)):
        mask[idx[pos] + 1:idx[pos + 1]] = True
    return mask


def speech_mask(db, frame_ms=FRAME_MS):
    """Boolean per-frame speech mask with an adaptive threshold."""
    if db.size == 0:
        return np.zeros(0, dtype=bool)
    # p5 approximates the noise floor even when the clip has few pauses
    thr = max(SILENCE_FLOOR_DB, float(np.percentile(db, 95)) - 30.0, float(np.percentile(db, 5)) + 6.0)
    mask = db > thr
    return _close_short_gaps(mask, int(120 / frame_ms))


def speech_bounds(x, sr):
    """Returns (start_s, end_s) of the first/last speech frame, or None if no speech."""
    x = to_mono(x)
    db, n = frame_db(x, sr)
    mask = speech_mask(db)
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return None
    return idx[0] * n / sr, (idx[-1] + 1) * n / sr


def _pause_runs(mask, min_frames):
    """Returns [(start_frame, end_frame)] of non-speech runs at least min_frames long."""
    runs = []
    start = None
    for i, v in enumerate(mask):
        if not v and start is None:
            start = i
        elif v and start is not None:
            if i - start >= min_frames:
                runs.append((start, i))
            start = None
    return runs


def pick_best_reference(x, sr, min_s=4.0, ideal_s=9.0, max_s=11.5, edge_pad_s=0.12):
    """Chooses the (start_s, end_s) passage of a recording to use as cloning reference.

    Edge silence is trimmed. If the speech is longer than max_s, the window with the
    densest speech closest to ideal_s is picked, cutting only in the middle of pauses so
    words are never chopped.
    """
    x = to_mono(x)
    total = len(x) / sr
    db, n = frame_db(x, sr)
    mask = speech_mask(db)
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return 0.0, min(total, max_s)

    frame_s = n / sr
    t0 = max(0.0, idx[0] * frame_s - edge_pad_s)
    t1 = min(total, (idx[-1] + 1) * frame_s + edge_pad_s)
    if t1 - t0 <= max_s:
        return t0, t1

    # Cut candidates: middle of each pause (>= 200 ms) plus the padded speech edges
    min_pause = int(200 / FRAME_MS)
    cuts = [(t0, 0.8)]
    for a, b in _pause_runs(mask, min_pause):
        mid = (a + b) / 2 * frame_s
        if t0 < mid < t1:
            cuts.append((mid, min((b - a) * frame_s, 0.8)))
    cuts.append((t1, 0.8))

    cs = np.concatenate([[0], np.cumsum(mask.astype(np.int64))])

    def speech_ratio(a_s, b_s):
        fa = int(a_s / frame_s)
        fb = max(fa + 1, int(b_s / frame_s))
        fb = min(fb, len(mask))
        return (cs[fb] - cs[fa]) / max(1, fb - fa)

    best, best_score = None, -1e9
    for i in range(len(cuts)):
        for j in range(i + 1, len(cuts)):
            dur = cuts[j][0] - cuts[i][0]
            if dur > max_s:
                break
            if dur < min_s:
                continue
            score = (speech_ratio(cuts[i][0], cuts[j][0])
                     - 0.03 * abs(dur - ideal_s)
                     + 0.05 * (cuts[i][1] + cuts[j][1]))
            if score > best_score:
                best, best_score = (cuts[i][0], cuts[j][0]), score
    if best is not None:
        return best

    # No clean pair of pauses (continuous speech): cut at the quietest spot near max_s
    end = min(t0 + max_s, t1)
    lo = max(int((end - 1.5) / frame_s), int(t0 / frame_s) + 1)
    hi = min(int(end / frame_s), len(db))
    if hi > lo:
        end = (lo + int(np.argmin(db[lo:hi]))) * frame_s
    return t0, end


def analyze_reference(x, sr):
    """Advisory quality check of a reference clip. Returns metrics and PT-BR warnings."""
    x = to_mono(x)
    duration = len(x) / sr
    warnings = []
    if len(x) == 0:
        return {"duration": 0.0, "speech_seconds": 0.0, "peak_db": -120.0, "clipping_ratio": 0.0,
                "snr_db": 0.0, "warnings": ["Áudio de referência vazio."]}

    db, n = frame_db(x, sr)
    mask = speech_mask(db)
    speech_seconds = float(mask.sum() * n / sr)
    peak = float(np.max(np.abs(x)))
    peak_db = 20.0 * np.log10(peak + 1e-10)
    clipping_ratio = float(np.mean(np.abs(x) >= 0.999))

    if mask.any():
        speech_level = float(np.percentile(db[mask], 90))
        noise_floor = float(np.percentile(db[~mask], 50)) if (~mask).any() else float(np.percentile(db, 5))
        snr_db = speech_level - max(noise_floor, -80.0)
    else:
        snr_db = 0.0

    if speech_seconds < 3.0:
        warnings.append(f"Pouca fala na referência ({speech_seconds:.1f}s). O ideal é de 5 a 12 segundos de fala limpa.")
    elif duration > 0 and speech_seconds / duration < 0.5:
        warnings.append("Mais da metade da referência é silêncio; corte as pausas longas para melhorar a clonagem.")
    if clipping_ratio > 0.001:
        warnings.append("A referência tem distorção (clipping). Grave com volume menor.")
    if peak_db < -30.0:
        warnings.append(f"Volume da referência muito baixo (pico {peak_db:.0f} dBFS).")
    if mask.any() and snr_db < 15.0:
        warnings.append(f"Muito ruído de fundo na referência (SNR ≈ {snr_db:.0f} dB). Prefira uma gravação mais limpa.")

    return {"duration": duration, "speech_seconds": speech_seconds, "peak_db": float(peak_db),
            "clipping_ratio": clipping_ratio, "snr_db": float(snr_db), "warnings": warnings}


def trim_edge_silence(x, sr, thr_db=-40.0, keep_ms=40):
    """Removes leading/trailing near-silence, keeping keep_ms of context on each side."""
    x = to_mono(x)
    n = max(1, int(sr * 0.01))
    frames = len(x) // n
    if frames == 0:
        return x
    levels = np.abs(x[:frames * n]).reshape(frames, n).max(axis=1)
    loud = np.flatnonzero(levels > _db_to_amp(thr_db))
    if loud.size == 0:
        return x
    keep = int(sr * keep_ms / 1000)
    return x[max(0, loud[0] * n - keep):min(len(x), (loud[-1] + 1) * n + keep)]


def normalize_peak(x, target_db=-2.0):
    """Peak-normalizes to target_db. Near-silent audio is left untouched."""
    x = np.asarray(x, dtype=np.float32)
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak < _db_to_amp(SILENCE_FLOOR_DB):
        return x
    return (x * (_db_to_amp(target_db) / peak)).astype(np.float32)


def apply_fade(x, sr, ms=8):
    """Short fade-in/out to avoid clicks at the edges."""
    x = np.asarray(x, dtype=np.float32).copy()
    n = min(int(sr * ms / 1000), len(x) // 2)
    if n > 0:
        ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
        x[:n] *= ramp
        x[-n:] *= ramp[::-1]
    return x


def crossfade_concat(chunks, sr, ms=50):
    """Joins audio chunks with a linear crossfade."""
    chunks = [np.asarray(c, dtype=np.float32) for c in chunks if c is not None and len(c) > 0]
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    out = chunks[0]
    for c in chunks[1:]:
        k = min(int(sr * ms / 1000), len(out), len(c))
        if k <= 0:
            out = np.concatenate([out, c])
            continue
        fade = np.linspace(0.0, 1.0, k, dtype=np.float32)
        mixed = out[-k:] * (1.0 - fade) + c[:k] * fade
        out = np.concatenate([out[:-k], mixed, c[k:]])
    return out


# --- Text helpers ---

_ABBREVIATIONS = r'(?:sr|sra|srta|dr|dra|prof|profa|av|etc|ex|exa|pág|art|vs|mr|mrs|ms|cap|tel|obs|ltda|nº|núm)'
_PLACEHOLDER = '\x00'


def _protect_periods(text):
    text = re.sub(r'\b(' + _ABBREVIATIONS + r')\.', lambda m: m.group(1) + _PLACEHOLDER, text, flags=re.IGNORECASE)
    return re.sub(r'(\d)\.(\d)', r'\1' + _PLACEHOLDER + r'\2', text)


def split_sentences(text):
    """Splits on . ! ? … while keeping abbreviations (Dr., Sra.) and decimals (3.5) intact."""
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []
    parts = re.split(r'(?<=[.!?…])["”’)]*\s+', _protect_periods(text))
    return [p.replace(_PLACEHOLDER, '.').strip() for p in parts if p.strip()]


def _split_long(sentence, max_chars):
    """Splits an over-long sentence at clause boundaries, then spaces, then hard cuts."""
    pieces = []
    rest = sentence
    while len(rest) > max_chars:
        window = rest[:max_chars + 1]
        cut = max(window.rfind(c) for c in ',;:—–') + 1
        if cut < max_chars * 0.4:
            cut = window.rfind(' ') + 1
        if cut < max_chars * 0.4:
            cut = max_chars
        pieces.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        pieces.append(rest)
    return pieces


def split_text_chunks(text, max_chars=250):
    """Splits text into chunks of at most max_chars, preferring sentence boundaries."""
    text = re.sub(r'\s+', ' ', text).strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return [text] if text else []

    chunks, current = [], ''
    for sentence in split_sentences(text):
        for piece in (_split_long(sentence, max_chars) if len(sentence) > max_chars else [sentence]):
            if current and len(current) + 1 + len(piece) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = f"{current} {piece}".strip()
    if current:
        chunks.append(current)
    return chunks


def normalize_text_pt(text, lang='pt_BR', lowercase=True):
    """Expands numbers/currency/percentages to words (Brazilian format) for TTS models.

    The F5-TTS pt-br checkpoint also needs lowercase input; other engines don't.
    """
    try:
        from num2words import num2words

        def parse_br_number(num_str):
            """Parses '1.500,50' / '1.500' / '3,5' / '2024' into (int_part, dec_part)."""
            if ',' in num_str:
                int_part, dec_part = num_str.split(',', 1)
                return int(int_part.replace('.', '')), dec_part
            if '.' in num_str:
                parts = num_str.split('.')
                # Dots in groups of 3 digits => thousands separator, otherwise decimal
                if all(len(p) == 3 for p in parts[1:]):
                    return int(num_str.replace('.', '')), None
                int_part, dec_part = num_str.split('.', 1)
                return int(int_part), dec_part
            return int(num_str), None

        number_pattern = r'\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?'

        def replace_currency(match):
            try:
                int_part, dec_part = parse_br_number(match.group(1))
                value = float(f"{int_part}.{dec_part or 0}")
                return num2words(value, lang=lang, to='currency')
            except Exception:
                return match.group()

        def replace_number(match):
            num_str = match.group()
            try:
                int_part, dec_part = parse_br_number(num_str)
                words = num2words(int_part, lang=lang)
                if dec_part:
                    words += " vírgula " + num2words(int(dec_part), lang=lang)
                return words
            except Exception:
                return num_str

        # Currency first (R$ 1.500,50 -> "mil e quinhentos reais e cinquenta centavos")
        text = re.sub(r'R\$\s*(' + number_pattern + r')', replace_currency, text, flags=re.IGNORECASE)
        # Then remaining numbers
        text = re.sub(number_pattern, replace_number, text)
        # Percent sign spoken out
        text = text.replace('%', ' por cento')
    except ImportError:
        print("Warning: num2words not installed, skipping number conversion")

    # Fix common Portuguese num2words quirks
    text = text.replace(" e um mil", " e mil")
    text = text.replace("um mil ", "mil ")

    return text.lower() if lowercase else text
