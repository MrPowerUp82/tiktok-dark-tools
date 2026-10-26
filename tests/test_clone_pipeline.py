"""Glue tests for the cloning pipeline in main.py, with the TTS engines replaced by fakes."""
import json
import os
import sys
import types
from unittest.mock import MagicMock

import numpy as np
import pytest

sf = pytest.importorskip("soundfile")
pytest.importorskip("eel")
pytest.importorskip("imageio_ffmpeg")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SR = 24000
RNG = np.random.default_rng(1)


def tone(seconds, level_db=-20.0):
    t = np.arange(int(SR * seconds)) / SR
    wave = np.sin(2 * np.pi * 220 * t) * (1 + 0.5 * np.sin(2 * np.pi * 3 * t))
    return (wave / np.max(np.abs(wave)) * 10 ** (level_db / 20)).astype(np.float32)


def gap(seconds):
    return (RNG.standard_normal(int(SR * seconds)) * 1e-4).astype(np.float32)


@pytest.fixture
def long_ref(tmp_path):
    """~27s recording: six 3.5s phrases separated by 0.5s pauses."""
    parts = [gap(0.5)]
    for _ in range(6):
        parts += [tone(3.5), gap(0.5)]
    path = tmp_path / "ref_long.wav"
    sf.write(path, np.concatenate(parts), SR)
    return str(path)


@pytest.fixture
def main_mod(monkeypatch, tmp_path):
    import main
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(main, "eel", MagicMock())
    monkeypatch.setattr(main, "_web_temp_dir", lambda: str(temp))
    main.ref_transcript_cache.clear()
    main.omnivoice_cache.clear()
    main.f5tts_cache.clear()
    main.cancel_requested = False
    return main


def install_fake_omnivoice(monkeypatch, calls, on_generate=None):
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    torch.float16 = "float16"
    torch.float32 = "float32"
    torch.manual_seed = lambda seed: calls["seeds"].append(seed)

    class FakeOmniVoice:
        @classmethod
        def from_pretrained(cls, repo, device_map, dtype):
            calls["loaded"].append((repo, device_map, dtype))
            return cls()

        def generate(self, text, ref_audio, ref_text, num_step, speed):
            calls["texts"].append(text)
            calls["ref_texts"].append(ref_text)
            calls["ref_audio"].append(ref_audio)
            if on_generate:
                on_generate()
            return [np.concatenate([gap(0.3), tone(1.0), gap(0.3)])]

    omni = types.ModuleType("omnivoice")
    omni.OmniVoice = FakeOmniVoice
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "omnivoice", omni)


def new_calls():
    return {"seeds": [], "loaded": [], "texts": [], "ref_texts": [], "ref_audio": []}


def clone_options(ref, out_dir, **overrides):
    options = {
        "refAudio": ref, "refText": "texto digitado pelo usuario", "genText": "Olá mundo.",
        "outputDir": str(out_dir), "fileName": "out", "engine": "omnivoice", "language": "pt",
        "removeNoise": False, "trimRef": True, "postProcess": True, "nfeStep": 16, "seed": 7, "speed": 1.0,
    }
    options.update(overrides)
    return options


def test_prepare_selects_passage_inside_engine_limits(main_mod, long_ref):
    info = main_mod.prepare_reference_audio(long_ref, engine="f5", select_best=True)
    assert 4.0 <= info["duration"] <= 11.6
    assert info["dropped_speech"] is True
    data, sr = sf.read(info["path"])
    assert sr == SR
    assert 20 * np.log10(np.max(np.abs(data))) == pytest.approx(-3.0, abs=0.1)

    omni = main_mod.prepare_reference_audio(long_ref, engine="omnivoice", select_best=True)
    assert omni["duration"] <= 10.1


def test_prepare_without_selection_keeps_everything_and_warns(main_mod, long_ref):
    info = main_mod.prepare_reference_audio(long_ref, engine="f5", select_best=False)
    assert info["dropped_speech"] is False
    assert info["duration"] > 20
    assert any("tende a piorar" in w for w in info["warnings"])


def test_denoise_is_skipped_for_clean_reference(main_mod, long_ref):
    pytest.importorskip("noisereduce")
    info = main_mod.prepare_reference_audio(long_ref, engine="f5", select_best=True, denoise=True)
    assert info["denoised"] is False  # synthetic clip is already very clean


def test_analyze_reference_reports_selected_passage(main_mod, long_ref):
    result = main_mod.analyze_reference(long_ref, "f5", True)
    assert result["ok"] and "será usado o trecho" in result["summary"]
    json.dumps(result)  # the result crosses the eel/JSON bridge
    assert main_mod.analyze_reference("nao_existe.wav")["ok"] is False


def test_omnivoice_chunks_long_text_with_one_seed_and_retranscribes(main_mod, monkeypatch, long_ref, tmp_path):
    calls = new_calls()
    install_fake_omnivoice(monkeypatch, calls)
    monkeypatch.setattr(main_mod, "_transcribe_audio", lambda path, lang: "texto do trecho escolhido")
    text = " ".join(f"Esta é a frase número {i} do roteiro de teste." for i in range(30))

    main_mod.clone_worker(clone_options(long_ref, tmp_path, genText=text))

    assert not main_mod.eel.task_failed.called, main_mod.eel.task_failed.call_args
    main_mod.eel.task_completed.assert_called_once()
    assert len(calls["texts"]) > 1 and all(len(t) <= main_mod.OMNIVOICE_MAX_CHUNK_CHARS for t in calls["texts"])
    assert calls["seeds"] == [7] * len(calls["texts"])
    # the reference was cut, so the typed text is replaced by the transcript of the chosen passage
    assert set(calls["ref_texts"]) == {"texto do trecho escolhido"}
    main_mod.eel.clone_ref_text_updated.assert_called_once_with("texto do trecho escolhido")
    data, sr = sf.read(tmp_path / "out.wav")
    assert sr == SR and len(data) > SR * len(calls["texts"]) * 0.8
    assert 20 * np.log10(np.max(np.abs(data))) == pytest.approx(-2.0, abs=0.1)  # post-processed


def test_user_transcript_is_kept_when_selection_was_auto_transcribed(main_mod, monkeypatch, long_ref, tmp_path):
    calls = new_calls()
    install_fake_omnivoice(monkeypatch, calls)
    retranscribe = MagicMock(return_value="nao deveria ser usado")
    monkeypatch.setattr(main_mod, "_transcribe_audio", retranscribe)
    main_mod.ref_transcript_cache[main_mod._ref_cache_key(long_ref, "omnivoice", True)] = "texto auto"

    main_mod.clone_worker(clone_options(long_ref, tmp_path, refText="texto corrigido pelo usuario"))

    assert not retranscribe.called
    assert calls["ref_texts"] == ["texto corrigido pelo usuario"]


def test_random_seed_is_shared_across_chunks(main_mod, monkeypatch, long_ref, tmp_path):
    calls = new_calls()
    install_fake_omnivoice(monkeypatch, calls)
    monkeypatch.setattr(main_mod, "_transcribe_audio", lambda path, lang: "ok")
    text = " ".join(f"Frase número {i} para dividir em vários trechos de áudio." for i in range(20))

    main_mod.clone_worker(clone_options(long_ref, tmp_path, genText=text, seed=-1))

    assert len(calls["seeds"]) > 1 and len(set(calls["seeds"])) == 1 and calls["seeds"][0] >= 0


def test_cancel_stops_between_chunks(main_mod, monkeypatch, long_ref, tmp_path):
    calls = new_calls()
    install_fake_omnivoice(monkeypatch, calls, on_generate=lambda: setattr(main_mod, "cancel_requested", True))
    monkeypatch.setattr(main_mod, "_transcribe_audio", lambda path, lang: "ok")
    text = " ".join(f"Frase número {i} para dividir em vários trechos de áudio." for i in range(20))

    main_mod.clone_worker(clone_options(long_ref, tmp_path, genText=text))

    assert len(calls["texts"]) == 1
    main_mod.eel.task_cancelled.assert_called_once()
    main_mod.eel.task_completed.assert_not_called()
    assert not (tmp_path / "out.wav").exists()


def test_missing_omnivoice_reports_install_hint(main_mod, monkeypatch, long_ref, tmp_path):
    torch = types.ModuleType("torch")
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "omnivoice", None)  # makes `from omnivoice import ...` raise ImportError
    monkeypatch.setattr(main_mod, "_transcribe_audio", lambda path, lang: "ok")

    main_mod.clone_worker(clone_options(long_ref, tmp_path))

    message = main_mod.eel.task_failed.call_args[0][0]
    assert "pip install omnivoice" in message


def test_f5_receives_new_parameters_and_output_is_postprocessed(main_mod, monkeypatch, long_ref, tmp_path):
    seen = {}

    class FakeF5:
        seed = 99

        def __init__(self, model, ckpt_file, device):
            seen["init"] = (model, ckpt_file, device)

        def infer(self, **kwargs):
            seen["infer"] = kwargs
            sf.write(kwargs["file_wave"], np.concatenate([gap(0.5), tone(2.0, -12.0), gap(0.5)]), SR)

    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    f5_pkg = types.ModuleType("f5_tts")
    f5_api = types.ModuleType("f5_tts.api")
    f5_api.F5TTS = FakeF5
    hub = types.ModuleType("huggingface_hub")
    hub.hf_hub_download = lambda repo_id, filename: "fake.safetensors"
    for name, mod in {"torch": torch, "f5_tts": f5_pkg, "f5_tts.api": f5_api, "huggingface_hub": hub}.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(main_mod, "_transcribe_audio", lambda path, lang: "Texto Do Trecho")

    main_mod.clone_worker(clone_options(long_ref, tmp_path, engine="f5", modelChoice="pt",
                                        cfgStrength=2.5, swayCoef=-0.5, genText="Preço: R$ 10,00."))

    assert not main_mod.eel.task_failed.called, main_mod.eel.task_failed.call_args
    kwargs = seen["infer"]
    assert kwargs["cfg_strength"] == 2.5 and kwargs["sway_sampling_coef"] == -0.5 and kwargs["seed"] == 7
    assert kwargs["nfe_step"] == 16
    assert kwargs["ref_text"] == "texto do trecho"  # pt-br checkpoint wants lowercase
    data, _ = sf.read(tmp_path / "out.wav")
    assert 20 * np.log10(np.max(np.abs(data))) == pytest.approx(-2.0, abs=0.1)
    assert len(data) / SR < 2.4  # edge silence trimmed from the 3s raw output
