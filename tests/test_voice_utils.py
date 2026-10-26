import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import voice_utils as vu

SR = 24000
RNG = np.random.default_rng(0)


def tone(seconds, level_db=-20.0):
    t = np.arange(int(SR * seconds)) / SR
    wave = np.sin(2 * np.pi * 220 * t) * (1 + 0.5 * np.sin(2 * np.pi * 3 * t))
    return (wave / np.max(np.abs(wave)) * 10 ** (level_db / 20)).astype(np.float32)


def gap(seconds, level_db=-80.0):
    return (RNG.standard_normal(int(SR * seconds)) * 10 ** (level_db / 20)).astype(np.float32)


def build(*parts):
    return np.concatenate(parts).astype(np.float32)


def test_speech_bounds_ignores_edge_silence():
    x = build(gap(1.0), tone(2.0), gap(1.0))
    start, end = vu.speech_bounds(x, SR)
    assert start == pytest.approx(1.0, abs=0.05)
    assert end == pytest.approx(3.0, abs=0.05)


def test_speech_bounds_none_for_silence():
    assert vu.speech_bounds(gap(2.0), SR) is None


def test_pick_best_reference_short_clip_only_trims_edges():
    x = build(gap(1.5), tone(5.0), gap(1.5))
    start, end = vu.pick_best_reference(x, SR)
    assert 1.2 <= start <= 1.5
    assert 6.5 <= end <= 6.8


def test_pick_best_reference_cuts_in_pauses_and_respects_max():
    # 6 phrases of 3s speech separated by 0.5s pauses = ~19s of speech
    parts = [gap(0.5)]
    for _ in range(6):
        parts += [tone(3.0), gap(0.5)]
    x = build(*parts)
    start, end = vu.pick_best_reference(x, SR, min_s=4, ideal_s=9, max_s=11.5)
    assert 4 <= end - start <= 11.5
    # both cuts must land inside a pause (silent region), never mid-phrase
    for cut in (start, end):
        i = int(cut * SR)
        window = x[max(0, i - 200): i + 200]
        assert np.max(np.abs(window)) < 10 ** (-60 / 20)


def test_pick_best_reference_prefers_dense_speech():
    # first 12s mostly silent with a short phrase, then a dense speech block
    x = build(gap(0.3), tone(1.5), gap(0.8), gap(5.0), tone(3.0), gap(0.4), tone(3.0), gap(0.4), tone(3.0), gap(0.3))
    start, end = vu.pick_best_reference(x, SR, min_s=4, ideal_s=9, max_s=11.5)
    assert start >= 7.0


def test_pick_best_reference_continuous_speech_falls_back():
    x = build(gap(0.3), tone(20.0), gap(0.3))
    start, end = vu.pick_best_reference(x, SR, max_s=11.5)
    assert end - start <= 11.5 + 1e-6
    assert end - start > 5


def test_analyze_reference_clean_has_no_warnings():
    x = build(gap(0.3), tone(6.0), gap(0.3))
    result = vu.analyze_reference(x, SR)
    assert result["warnings"] == []
    assert result["snr_db"] > 30


def test_analyze_reference_flags_problems():
    short = vu.analyze_reference(build(gap(1.0), tone(1.5), gap(1.0)), SR)
    assert any("Pouca fala" in w for w in short["warnings"])

    clipped = np.clip(build(tone(6.0, -20.0)) * 20, -1, 1)
    assert any("clipping" in w for w in vu.analyze_reference(clipped, SR)["warnings"])

    quiet = vu.analyze_reference(build(gap(0.3), tone(6.0, -45.0), gap(0.3)), SR)
    assert any("baixo" in w for w in quiet["warnings"])

    noisy = build(tone(6.0, -20.0)) + (RNG.standard_normal(6 * SR) * 10 ** (-28 / 20)).astype(np.float32)
    noisy = np.concatenate([gap(1.0, -28.0), noisy, gap(1.0, -28.0)])
    assert any("ruído" in w for w in vu.analyze_reference(noisy, SR)["warnings"])


def test_trim_edge_silence_keeps_context():
    x = build(gap(1.0), tone(2.0), gap(1.0))
    trimmed = vu.trim_edge_silence(x, SR, keep_ms=40)
    assert 2.0 <= len(trimmed) / SR <= 2.2


def test_trim_edge_silence_leaves_silence_alone():
    x = gap(1.0)
    assert len(vu.trim_edge_silence(x, SR)) == len(x)


def test_normalize_peak_and_silence_untouched():
    loud = vu.normalize_peak(tone(1.0, -20.0), target_db=-2.0)
    assert 20 * np.log10(np.max(np.abs(loud))) == pytest.approx(-2.0, abs=0.01)
    quiet = gap(1.0, -80.0)
    assert np.array_equal(vu.normalize_peak(quiet), quiet)


def test_apply_fade_zeroes_edges():
    faded = vu.apply_fade(np.ones(SR, dtype=np.float32), SR, ms=8)
    assert faded[0] == 0 and faded[-1] == 0 and faded[SR // 2] == 1


def test_crossfade_concat_length_and_continuity():
    a = np.ones(SR, dtype=np.float32)
    b = np.ones(SR, dtype=np.float32)
    out = vu.crossfade_concat([a, b], SR, ms=50)
    overlap = int(SR * 0.05)
    assert len(out) == 2 * SR - overlap
    assert np.allclose(out, 1.0, atol=1e-5)  # equal-level audio stays flat through the fade


def test_crossfade_concat_handles_empty_and_single():
    assert len(vu.crossfade_concat([], SR)) == 0
    assert len(vu.crossfade_concat([None, np.zeros(0)], SR)) == 0
    one = np.ones(100, dtype=np.float32)
    assert np.array_equal(vu.crossfade_concat([one], SR), one)


def test_split_sentences_protects_abbreviations_and_decimals():
    text = "O Dr. Silva pagou 3.5 mil reais. A Sra. Costa chegou! Tudo bem?"
    assert vu.split_sentences(text) == [
        "O Dr. Silva pagou 3.5 mil reais.",
        "A Sra. Costa chegou!",
        "Tudo bem?",
    ]


def test_split_text_chunks_short_text_is_one_chunk():
    assert vu.split_text_chunks("Olá mundo.", 250) == ["Olá mundo."]
    assert vu.split_text_chunks("   ", 250) == []


def test_split_text_chunks_respects_limit_and_loses_nothing():
    text = " ".join(f"Esta é a frase número {i}, com algumas palavras para encher." for i in range(30))
    chunks = vu.split_text_chunks(text, 120)
    assert all(len(c) <= 120 for c in chunks)
    assert " ".join(chunks) == text
    # chunks end on sentence boundaries when sentences fit
    assert all(c.endswith(".") for c in chunks)


def test_split_text_chunks_splits_overlong_sentence():
    sentence = ", ".join(f"palavra{i}" for i in range(60)) + "."
    chunks = vu.split_text_chunks(sentence, 100)
    assert all(len(c) <= 100 for c in chunks)
    assert len(chunks) > 1
    assert " ".join(chunks).replace(" ", "") == sentence.replace(" ", "")


def test_split_text_chunks_hard_cut_without_spaces():
    chunks = vu.split_text_chunks("a" * 250, 100)
    assert [len(c) for c in chunks] == [100, 100, 50]


def test_normalize_text_pt_lowercase_flag():
    assert vu.normalize_text_pt("Olá Mundo", lowercase=True) == "olá mundo"
    assert vu.normalize_text_pt("Olá Mundo", lowercase=False) == "Olá Mundo"


def test_normalize_text_pt_numbers():
    pytest.importorskip("num2words")
    out = vu.normalize_text_pt("Paguei R$ 1.500,50 e 10%", lowercase=False)
    assert "mil" in out and "por cento" in out and not any(ch.isdigit() for ch in out)
