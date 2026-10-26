import os
import sys

# Disable gevent compiled C accelerators to prevent Windows Application Control / WDAC DLL blocking
os.environ['GEVENT_PURE_PYTHON'] = '1'
# Enable CUDA libraries on Windows when installed via pip packages
dll_dirs = []
loaded_dlls = []

if sys.platform == 'win32':
    import site
    import ctypes
    packages = []
    try:
        packages.extend(site.getsitepackages())
    except AttributeError:
        pass
    if site.ENABLE_USER_SITE:
        packages.append(site.getusersitepackages())
    for path in sys.path:
        if 'site-packages' in path:
            packages.append(path)
            
    for p_dir in set(packages):
        nvidia_path = os.path.join(p_dir, 'nvidia')
        if not os.path.exists(nvidia_path):
            continue
            
        # 1. Register all directories in the DLL search path first
        cuda_packages = ['cuda_runtime', 'cublas', 'cudnn', 'cuda_nvrtc']
        for sub in cuda_packages:
            bin_dir = os.path.join(nvidia_path, sub, 'bin')
            if os.path.exists(bin_dir):
                try:
                    dll_dirs.append(os.add_dll_directory(bin_dir))
                except Exception:
                    pass
                    
        # 2. Preload the DLLs using ctypes to keep them cached in memory
        for sub in cuda_packages:
            bin_dir = os.path.join(nvidia_path, sub, 'bin')
            if os.path.exists(bin_dir):
                for file in os.listdir(bin_dir):
                    if file.lower().endswith('.dll'):
                        dll_path = os.path.join(bin_dir, file)
                        try:
                            loaded_dlls.append(ctypes.CDLL(dll_path))
                        except Exception:
                            pass

import random
import threading
import subprocess
import shutil
import tkinter as tk
from tkinter import filedialog
import eel
import numpy as np

import voice_utils

# Global variables to control background tasks and handle cancellation
active_thread = None
cancel_requested = False
ffmpeg_process = None

# Heavy model caches so repeated runs don't reload checkpoints from disk
f5tts_cache = {}          # (model_choice, device) -> F5TTS instance
omnivoice_cache = {}      # device_map -> OmniVoice instance
whisper_ref_model = None  # cached faster-whisper model for reference transcription
ref_transcript_cache = {} # (path, mtime, engine, select_best) -> auto-transcribed reference text

def is_audio_file(file_path):
    """Checks if the file extension corresponds to a supported audio format."""
    ext = os.path.splitext(file_path)[1].lower()
    return ext in ['.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac', '.wma', '.webm']

class CustomSegment:
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text

def create_custom_segment(words):
    start = words[0].start
    end = words[-1].end
    
    text = ""
    for i, w in enumerate(words):
        w_text = w.word
        if i > 0 and not w_text.startswith(" ") and not text.endswith(" "):
            text += " " + w_text
        else:
            text += w_text
    text = text.strip()
    return CustomSegment(start, end, text)

def make_tiktok_segments(segments, max_words=3, max_duration=1.5):
    """
    Groups words from faster-whisper segments into shorter segments suitable for TikTok.
    """
    current_words = []
    current_start = None
    
    for segment in segments:
        words = getattr(segment, 'words', None)
        if not words:
            # Fallback if no word timestamps are available
            if current_words:
                yield create_custom_segment(current_words)
                current_words = []
                current_start = None
            yield segment
            continue
            
        for w in words:
            w_start = w.start
            w_end = w.end
            
            if current_start is None:
                current_start = w_start
            
            current_words.append(w)
            
            # Check if we reached the limits
            duration = w_end - current_start
            if len(current_words) >= max_words or duration >= max_duration:
                yield create_custom_segment(current_words)
                current_words = []
                current_start = None
                
    if current_words:
        yield create_custom_segment(current_words)

def format_time_srt(seconds):
    """Formats seconds into SRT subtitle timestamp format (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def format_time_vtt(seconds):
    """Formats seconds into WebVTT subtitle timestamp format (HH:MM:SS.mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"

def write_txt(segments, path):
    """Writes the transcription segments to a plain text file."""
    with open(path, 'w', encoding='utf-8') as f:
        for seg in segments:
            f.write(f"{seg.text.strip()}\n")

def write_srt(segments, path):
    """Writes the transcription segments to an SRT subtitle file."""
    with open(path, 'w', encoding='utf-8') as f:
        for idx, seg in enumerate(segments, 1):
            f.write(f"{idx}\n")
            f.write(f"{format_time_srt(seg.start)} --> {format_time_srt(seg.end)}\n")
            f.write(f"{seg.text.strip()}\n\n")

def write_vtt(segments, path):
    """Writes the transcription segments to a WebVTT subtitle file."""
    with open(path, 'w', encoding='utf-8') as f:
        f.write("WEBVTT\n\n")
        for seg in segments:
            f.write(f"{format_time_vtt(seg.start)} --> {format_time_vtt(seg.end)}\n")
            f.write(f"{seg.text.strip()}\n\n")

def cleanup_temp(path, temp_created):
    """Safely deletes temporary files generated during the process."""
    if temp_created and path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception as e:
            print(f"Error deleting temp file {path}: {e}")

def run_ffmpeg_extract(video_path, output_path, format_type):
    """Extracts audio from video using imageio-ffmpeg and parses output for progress."""
    global ffmpeg_process, cancel_requested
    import imageio_ffmpeg
    
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg_exe, '-y', '-i', video_path, '-vn']
    
    if format_type == 'wav':
        # 16kHz mono is optimized for transcription
        cmd.extend(['-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', output_path])
    elif format_type == 'mp3':
        # High quality stereo MP3 for general listening
        cmd.extend(['-acodec', 'libmp3lame', '-ab', '192k', output_path])
    else:
        cmd.extend([output_path])
        
    ffmpeg_process = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE, 
        text=True, 
        encoding='utf-8', 
        errors='ignore',
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    )
    
    duration = None
    while True:
        if cancel_requested:
            ffmpeg_process.terminate()
            ffmpeg_process.wait()
            raise Exception("Process cancelled by user.")
            
        line = ffmpeg_process.stderr.readline()
        if not line:
            break
            
        # Parse video/audio duration
        if "Duration:" in line and not duration:
            try:
                parts = line.split("Duration:")[1].split(",")[0].strip().split(":")
                duration = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            except Exception:
                pass
                
        # Parse current progress time
        if "time=" in line and duration:
            try:
                time_str = line.split("time=")[1].split()[0].strip()
                parts = time_str.split(":")
                current_time = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                progress = min(100, int((current_time / duration) * 100))
                eel.update_progress('audio', progress, f"Extracting audio: {progress}%")()
            except Exception:
                pass
                
    ffmpeg_process.wait()
    if ffmpeg_process.returncode != 0 and not cancel_requested:
        raise Exception(f"FFmpeg extraction failed with exit code {ffmpeg_process.returncode}")
    ffmpeg_process = None

@eel.expose
def select_file():
    """Opens a native system file selection dialog."""
    root = tk.Tk()
    root.withdraw()
    root.wm_attributes('-topmost', 1)
    
    file_path = filedialog.askopenfilename(
        title="Select Video or Audio File",
        filetypes=[
            ("Media files", "*.mp4 *.avi *.mkv *.mov *.mp3 *.wav *.m4a *.flac *.webm *.ogg"),
            ("All files", "*.*")
        ]
    )
    root.destroy()
    return file_path

@eel.expose
def select_folder():
    """Opens a native system folder selection dialog."""
    root = tk.Tk()
    root.withdraw()
    root.wm_attributes('-topmost', 1)
    
    folder_path = filedialog.askdirectory(title="Select Output Directory")
    root.destroy()
    return folder_path

@eel.expose
def open_output_dir(path):
    """Opens the target directory in the file explorer."""
    if os.path.exists(path):
        if sys.platform == 'win32':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.run(['open', path])
        else:
            subprocess.run(['xdg-open', path])
        return True
    return False

@eel.expose
def cancel_task():
    """Flags cancellation request for the active background processes."""
    global cancel_requested, ffmpeg_process
    cancel_requested = True
    if ffmpeg_process:
        try:
            ffmpeg_process.terminate()
        except Exception:
            pass
    return True

@eel.expose
def start_process(options):
    """Starts the extraction/transcription worker thread."""
    global active_thread, cancel_requested
    if active_thread and active_thread.is_alive():
        return "A task is already in progress."
    
    cancel_requested = False
    active_thread = threading.Thread(target=process_worker, args=(options,))
    active_thread.start()
    return "Started"

def process_worker(options):
    """Main worker executing the audio extraction and/or transcription tasks."""
    global cancel_requested
    input_file = options.get('inputFile')
    output_dir = options.get('outputDir')
    action = options.get('action')  # 'audio', 'transcribe', 'both'
    audio_format = options.get('audioFormat', 'mp3')
    model_size = options.get('modelSize', 'base')
    language = options.get('language', 'auto')
    device = options.get('device', 'cpu')
    compute_type = options.get('computeType', 'int8')
    export_formats = options.get('exportFormats', ['txt'])
    tiktok_style = options.get('tiktokStyle', False)
    tiktok_max_words = int(options.get('tiktokMaxWords', 3))
    tiktok_max_duration = float(options.get('tiktokMaxDuration', 1.5))

    if not input_file or not os.path.exists(input_file):
        eel.task_failed("Input file does not exist.")()
        return

    if not output_dir or not os.path.exists(output_dir):
        output_dir = os.path.dirname(input_file)

    base_name = os.path.splitext(os.path.basename(input_file))[0]
    audio_path = None
    temp_audio_created = False
    
    try:
        is_input_audio = is_audio_file(input_file)
        
        # --- PHASE 1: AUDIO EXTRACTION ---
        if not is_input_audio:
            if action in ['audio', 'both']:
                # Save audio format requested by user
                audio_path = os.path.join(output_dir, f"{base_name}.{audio_format}")
                eel.update_status("Extracting audio stream from video...")()
                run_ffmpeg_extract(input_file, audio_path, audio_format)
            elif action == 'transcribe':
                # Use a temp WAV file optimized for whisper
                audio_path = os.path.join(output_dir, f"_temp_{base_name}.wav")
                temp_audio_created = True
                eel.update_status("Extracting audio stream for transcription...")()
                run_ffmpeg_extract(input_file, audio_path, 'wav')
        else:
            # Input is already audio
            if action == 'audio':
                dest_path = os.path.join(output_dir, os.path.basename(input_file))
                if os.path.abspath(input_file) != os.path.abspath(dest_path):
                    eel.update_status("Copying audio file to output folder...")()
                    shutil.copy(input_file, dest_path)
                audio_path = dest_path
                eel.update_progress('audio', 100, "Audio file saved.")()
            else:
                audio_path = input_file

        if cancel_requested:
            cleanup_temp(audio_path, temp_audio_created)
            eel.task_cancelled()()
            return

        # --- PHASE 2: TRANSCRIPTION ---
        if action in ['transcribe', 'both']:
            # Import faster-whisper lazily to make app boot time faster
            eel.update_status(f"Loading faster-whisper '{model_size}' model on {device} ({compute_type})...")()
            from faster_whisper import WhisperModel
            
            # Instantiate model
            try:
                model = WhisperModel(model_size, device=device, compute_type=compute_type)
            except Exception as e:
                # If CUDA failed, fallback to CPU
                if device == 'cuda':
                    eel.update_status("CUDA execution failed. Falling back to CPU...")()
                    model = WhisperModel(model_size, device='cpu', compute_type='int8')
                else:
                    raise e
            
            if cancel_requested:
                cleanup_temp(audio_path, temp_audio_created)
                eel.task_cancelled()()
                return

            eel.update_status("Transcribing audio content...")()
            
            transcribe_args = {"beam_size": 5}
            if language and language != 'auto':
                transcribe_args["language"] = language

            if tiktok_style:
                transcribe_args["word_timestamps"] = True

            segments, info = model.transcribe(audio_path, **transcribe_args)
            total_duration = info.duration
            transcribed_segments = []
            
            if tiktok_style:
                segments = make_tiktok_segments(segments, max_words=tiktok_max_words, max_duration=tiktok_max_duration)
            
            # Read from generator to perform actual processing
            for segment in segments:
                if cancel_requested:
                    cleanup_temp(audio_path, temp_audio_created)
                    eel.task_cancelled()()
                    return
                
                transcribed_segments.append(segment)
                progress = min(100, int((segment.end / total_duration) * 100))
                eel.update_progress('transcribe', progress, f"Transcribing: {progress}% ({segment.end:.1f}s / {total_duration:.1f}s)")()
                
                # Send text segment to the UI in real-time
                eel.new_segment({
                    'start': segment.start,
                    'end': segment.end,
                    'text': segment.text
                })()

            # Output transcribing text formats
            eel.update_status("Writing transcript files...")()
            if not export_formats:
                export_formats = ['txt']
                
            for fmt in export_formats:
                out_path = os.path.join(output_dir, f"{base_name}.{fmt}")
                if fmt == 'txt':
                    write_txt(transcribed_segments, out_path)
                elif fmt == 'srt':
                    write_srt(transcribed_segments, out_path)
                elif fmt == 'vtt':
                    write_vtt(transcribed_segments, out_path)
                    
        # Cleanup temp file if created
        cleanup_temp(audio_path, temp_audio_created)
        
        # Complete
        status_msg = "Task finished successfully!"
        if action == 'audio':
            status_msg = "Audio extracted successfully!"
        elif action == 'transcribe':
            status_msg = "Transcription completed successfully!"
        else:
            status_msg = "Audio extracted and transcribed successfully!"
            
        eel.task_completed(status_msg)()
        
    except Exception as e:
        cleanup_temp(audio_path, temp_audio_created)
        import traceback
        traceback.print_exc()
        eel.task_failed(str(e))()

@eel.expose
def get_voices():
    """Fetches Microsoft Edge TTS voices, with localization and online/offline handling."""
    try:
        import asyncio
        import edge_tts
        async def fetch_voices():
            voices = await edge_tts.VoicesManager.create()
            return [
                {
                    'name': v['Name'],
                    'shortName': v['ShortName'],
                    'gender': v['Gender'],
                    'locale': v['Locale'],
                    'friendlyName': f"{v['Locale']} - {v['ShortName'].split('-')[-1]} ({v['Gender']})"
                }
                for v in voices.voices
            ]
            
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        res = loop.run_until_complete(fetch_voices())
        loop.close()
        return res
    except Exception as e:
        print("Error fetching edge-tts voices:", e)
        # Fallback list of common voices
        return [
            {'shortName': 'pt-BR-FranciscaNeural', 'friendlyName': 'pt-BR - Francisca (Female)', 'locale': 'pt-BR', 'gender': 'Female'},
            {'shortName': 'pt-BR-AntonioNeural', 'friendlyName': 'pt-BR - Antonio (Male)', 'locale': 'pt-BR', 'gender': 'Male'},
            {'shortName': 'en-US-AriaNeural', 'friendlyName': 'en-US - Aria (Female)', 'locale': 'en-US', 'gender': 'Female'},
            {'shortName': 'en-US-GuyNeural', 'friendlyName': 'en-US - Guy (Male)', 'locale': 'en-US', 'gender': 'Male'},
            {'shortName': 'es-ES-ElviraNeural', 'friendlyName': 'es-ES - Elvira (Female)', 'locale': 'es-ES', 'gender': 'Female'},
            {'shortName': 'es-ES-AlvaroNeural', 'friendlyName': 'es-ES - Alvaro (Male)', 'locale': 'es-ES', 'gender': 'Male'}
        ]

def tts_worker(options):
    """Worker executing speech synthesis in the background."""
    global cancel_requested
    text = options.get('text')
    voice = options.get('voice')
    output_dir = options.get('outputDir')
    file_name = options.get('fileName', 'speech')
    rate = options.get('rate', '+0%')
    pitch = options.get('pitch', '+0Hz')
    
    if not text:
        eel.task_failed("Text cannot be empty.")()
        return
        
    if not output_dir or not os.path.exists(output_dir):
        # Default to user's Documents folder if output_dir is empty
        output_dir = os.path.join(os.path.expanduser('~'), 'Documents')
        os.makedirs(output_dir, exist_ok=True)
        
    output_path = os.path.join(output_dir, f"{file_name}.mp3")
    
    try:
        import asyncio
        import edge_tts
        
        eel.update_status("Initializing TTS engine...")()
        
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        
        eel.update_status("Synthesizing speech from text...")()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(communicate.save(output_path))
        loop.close()
        
        if cancel_requested:
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except Exception:
                    pass
            eel.task_cancelled()()
            return
            
        # Copy to web temp folder for playing in UI player
        web_temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web', 'temp')
        os.makedirs(web_temp_dir, exist_ok=True)
        web_temp_path = os.path.join(web_temp_dir, 'playback.mp3')
        try:
            shutil.copy(output_path, web_temp_path)
        except Exception as e:
            print("Error copying to temp playback:", e)
            
        eel.task_completed(f"Speech generated successfully as: {os.path.basename(output_path)}")()
        eel.tts_completed("temp/playback.mp3")()
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        eel.task_failed(str(e))()

@eel.expose
def generate_tts(options):
    """Starts the speech synthesis background thread."""
    global active_thread, cancel_requested
    if active_thread and active_thread.is_alive():
        return "A task is already in progress."
        
    cancel_requested = False
    active_thread = threading.Thread(target=tts_worker, args=(options,))
    active_thread.start()
    return "Started"

# Reference passage length limits per engine, in seconds: (min, ideal, max).
# F5-TTS clips references over ~12s on its own, which desyncs the reference text;
# OmniVoice recommends 3-10s clips.
ENGINE_REF_LIMITS = {
    'f5': (4.0, 9.0, 11.5),
    'omnivoice': (3.0, 7.0, 10.0),
}
REF_SCAN_SECONDS = 300          # only the first 5 minutes of a reference file are analysed
DENOISE_SKIP_SNR_DB = 35.0      # already-clean references are not denoised (avoids artifacts)
OMNIVOICE_MAX_CHUNK_CHARS = 250
OMNIVOICE_REPO = "k2-fsa/OmniVoice"
SAMPLE_RATE = 24000

def _web_temp_dir():
    temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web', 'temp')
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir

def _ref_cache_key(audio_path, engine, select_best):
    """Identifies a (file, engine, selection mode) so a transcript can be matched to the exact passage used."""
    try:
        mtime = os.path.getmtime(audio_path)
    except OSError:
        mtime = 0
    return (os.path.abspath(audio_path), mtime, engine, bool(select_best))

def prepare_reference_audio(audio_path, engine='f5', select_best=True, denoise=False):
    """Builds the reference clip: mono 24kHz WAV, best passage for the engine (cut only inside
    pauses), optional denoise and peak normalization. Whisper, noise reduction and the TTS engine
    all consume this exact audio. Returns an info dict (see keys below)."""
    import imageio_ffmpeg
    import soundfile as sf

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    temp_dir = _web_temp_dir()
    full_path = os.path.join(temp_dir, 'ref_full.wav')
    out_path = os.path.join(temp_dir, 'ref_prepared.wav')

    cmd = [ffmpeg_exe, '-y', '-i', audio_path, '-t', str(REF_SCAN_SECONDS),
           '-ac', '1', '-ar', str(SAMPLE_RATE), '-acodec', 'pcm_s16le', full_path]
    result = subprocess.run(
        cmd, capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    )
    if result.returncode != 0 or not os.path.exists(full_path):
        print("ffmpeg reference conversion failed, falling back to original file")
        return {'path': audio_path, 'start': 0.0, 'end': None, 'source_duration': None, 'duration': None,
                'dropped_speech': False, 'denoised': False, 'warnings': [], 'analysis': None}

    data, sr = sf.read(full_path, dtype='float32')
    data = voice_utils.to_mono(data)
    total = len(data) / sr
    min_s, ideal_s, max_s = ENGINE_REF_LIMITS.get(engine, ENGINE_REF_LIMITS['f5'])

    bounds = voice_utils.speech_bounds(data, sr)
    if select_best:
        start, end = voice_utils.pick_best_reference(data, sr, min_s, ideal_s, max_s)
    else:
        start, end = 0.0, total
    start, end = float(start), float(end)  # plain floats: these cross the eel/JSON bridge
    segment = data[int(start * sr):int(end * sr)]
    dropped_speech = bool(bounds and (bounds[0] < start - 0.3 or bounds[1] > end + 0.3))

    analysis = voice_utils.analyze_reference(segment, sr)
    warnings = list(analysis['warnings'])
    if not select_best and total > max_s + 0.5:
        warnings.append(f"Referência com {total:.0f}s: acima de ~{max_s:.0f}s a clonagem tende a piorar. "
                        "Ative a seleção do melhor trecho.")

    denoised = False
    if denoise and analysis['snr_db'] < DENOISE_SKIP_SNR_DB:
        try:
            import noisereduce as nr
            segment = nr.reduce_noise(y=segment, sr=sr, prop_decrease=0.85).astype('float32')
            denoised = True
        except Exception as nr_err:
            print("Failed to reduce noise:", nr_err)

    segment = voice_utils.normalize_peak(segment, -3.0)
    sf.write(out_path, segment, sr, subtype='PCM_16')
    return {'path': out_path, 'start': start, 'end': end, 'source_duration': total,
            'duration': len(segment) / sr, 'dropped_speech': dropped_speech, 'denoised': denoised,
            'warnings': warnings, 'analysis': analysis}

def postprocess_output(path):
    """Trims edge silence, normalizes the peak and fades the edges of a generated WAV in place."""
    import soundfile as sf
    data, sr = sf.read(path, dtype='float32')
    data = voice_utils.to_mono(data)
    data = voice_utils.trim_edge_silence(data, sr, thr_db=-40.0, keep_ms=60)
    data = voice_utils.apply_fade(voice_utils.normalize_peak(data, -2.0), sr)
    sf.write(path, data, sr, subtype='PCM_16')

def _get_whisper_ref_model():
    """Returns the cached faster-whisper model used for reference transcription."""
    global whisper_ref_model
    if whisper_ref_model is None:
        from faster_whisper import WhisperModel
        # Use small model for fast reference audio transcription (cached between calls)
        device = 'cuda' if len(dll_dirs) > 0 else 'cpu'
        compute_type = 'float16' if device == 'cuda' else 'int8'
        eel.update_status("Loading Whisper model for auto-transcription...")()
        try:
            whisper_ref_model = WhisperModel("small", device=device, compute_type=compute_type)
        except Exception:
            eel.update_status("CUDA failed for Whisper. Falling back to CPU...")()
            whisper_ref_model = WhisperModel("small", device='cpu', compute_type='int8')
    return whisper_ref_model

def _transcribe_audio(path, language='auto'):
    model = _get_whisper_ref_model()
    transcribe_args = {"beam_size": 5}
    if language and language != 'auto':
        transcribe_args["language"] = language
    segments, _info = model.transcribe(path, **transcribe_args)
    return " ".join(seg.text.strip() for seg in segments).strip()

@eel.expose
def analyze_reference(audio_path, engine='f5', trim=True):
    """Reports which passage of the reference will be used and any quality problems."""
    if not audio_path or not os.path.exists(audio_path):
        return {'ok': False, 'message': "Arquivo não encontrado."}
    try:
        info = prepare_reference_audio(audio_path, engine=engine, select_best=trim)
    except Exception as e:
        return {'ok': False, 'message': f"Falha ao analisar a referência: {e}"}
    if info['source_duration'] is None:
        return {'ok': True, 'summary': "Não foi possível analisar o áudio; ele será usado como está.", 'warnings': []}
    if info['dropped_speech']:
        summary = (f"Referência de {info['source_duration']:.1f}s: será usado o trecho "
                   f"{info['start']:.1f}s–{info['end']:.1f}s ({info['duration']:.1f}s).")
    else:
        summary = f"Referência de {info['source_duration']:.1f}s: será usada inteira (sem silêncio nas bordas)."
    return {'ok': True, 'summary': summary, 'warnings': info['warnings']}

@eel.expose
def transcribe_reference(audio_path, language='auto', trim=True, engine='f5'):
    """Transcribes the reference passage the cloning step will use, with faster-whisper."""
    if not audio_path or not os.path.exists(audio_path):
        return "Error: File does not exist."

    try:
        eel.update_status("Preparando áudio de referência...")()
        prepared = prepare_reference_audio(audio_path, engine=engine, select_best=trim)

        eel.update_status("Transcribing reference audio...")()
        text = _transcribe_audio(prepared['path'], language)
        ref_transcript_cache[_ref_cache_key(audio_path, engine, trim)] = text

        eel.update_status("Auto-transcription complete.")()
        return text
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Error transcribing reference audio: {str(e)}"

def _to_numpy_audio(audio):
    """Converts an engine output (tensor or ndarray, any leading dims) to a mono float32 array."""
    if hasattr(audio, 'detach'):
        audio = audio.detach().cpu().numpy()
    return voice_utils.to_mono(np.squeeze(np.asarray(audio)))

def _synthesize_f5(ref_file, ref_text, gen_text, output_path, p):
    """Runs F5-TTS. Returns the seed used."""
    import torch
    from f5_tts.api import F5TTS

    device = "cuda" if torch.cuda.is_available() else "cpu"

    # Reuse a cached model instance when possible (loading takes tens of seconds)
    cache_key = (p['model_choice'], device)
    tts = f5tts_cache.get(cache_key)
    if tts is None:
        if p['model_choice'] == 'pt':
            eel.update_status("Carregando modelo em Português (firstpixel/F5-TTS-pt-br)...")()
            from huggingface_hub import hf_hub_download
            ckpt_path = hf_hub_download(repo_id="firstpixel/F5-TTS-pt-br", filename="pt-br/model_last.safetensors")
            model_type = "F5TTS_Base"
        else:
            eel.update_status("Loading standard F5-TTS model (English/Chinese)...")()
            ckpt_path = ""
            model_type = "F5TTS_v1_Base"

        tts = F5TTS(model=model_type, ckpt_file=ckpt_path, device=device)
        f5tts_cache[cache_key] = tts
    else:
        eel.update_status("Modelo F5-TTS já em memória, reutilizando...")()

    if cancel_requested:
        return None

    # The pt-br checkpoint requires lowercase text with numbers written as words
    if p['model_choice'] == 'pt':
        eel.update_status("Pré-processando texto para o modelo Português...")()
        ref_text = voice_utils.normalize_text_pt(ref_text, lang='pt_BR', lowercase=True)
        gen_text = voice_utils.normalize_text_pt(gen_text, lang='pt_BR', lowercase=True)
        print("Preprocessed ref_text:", ref_text[:200])
        print("Preprocessed gen_text:", gen_text[:200])

    eel.update_status(f"Clonando a voz com F5-TTS ({device.upper()}, NFE {p['nfe_step']}, {p['speed']:.2f}x)...")()
    infer_kwargs = {
        "ref_file": ref_file,
        "ref_text": ref_text,
        "gen_text": gen_text,
        "file_wave": output_path,
        "nfe_step": p['nfe_step'],
        "speed": p['speed'],
        "remove_silence": p['remove_silence'],
        "cfg_strength": p['cfg_strength'],
        "sway_sampling_coef": p['sway_coef'],
    }
    if p['seed'] >= 0:
        infer_kwargs["seed"] = p['seed']
    try:
        tts.infer(**infer_kwargs)
    except TypeError:
        # Older f5-tts releases don't accept some kwargs; retry with the basic call
        tts.infer(ref_file=ref_file, ref_text=ref_text, gen_text=gen_text, file_wave=output_path)
    return getattr(tts, 'seed', None)

def _synthesize_omnivoice(ref_file, ref_text, gen_text, output_path, p):
    """Runs OmniVoice (k2-fsa) zero-shot cloning, chunking long text. Returns the seed used."""
    import torch
    import soundfile as sf
    try:
        from omnivoice import OmniVoice
    except ImportError:
        raise Exception("O OmniVoice não está instalado. Instale com: pip install omnivoice")

    use_cuda = torch.cuda.is_available()
    device_map = "cuda:0" if use_cuda else "cpu"
    model = omnivoice_cache.get(device_map)
    if model is None:
        eel.update_status(f"Carregando OmniVoice ({OMNIVOICE_REPO}) — o primeiro uso baixa o modelo...")()
        model = OmniVoice.from_pretrained(
            OMNIVOICE_REPO, device_map=device_map,
            dtype=torch.float16 if use_cuda else torch.float32
        )
        omnivoice_cache[device_map] = model
    else:
        eel.update_status("OmniVoice já em memória, reutilizando...")()

    if cancel_requested:
        return None

    # OmniVoice handles casing itself; only spell out numbers for Portuguese text
    if p['language'] == 'pt':
        ref_text = voice_utils.normalize_text_pt(ref_text, lang='pt_BR', lowercase=False)
        gen_text = voice_utils.normalize_text_pt(gen_text, lang='pt_BR', lowercase=False)

    chunks = voice_utils.split_text_chunks(gen_text, OMNIVOICE_MAX_CHUNK_CHARS)
    if not chunks:
        raise Exception("O texto a sintetizar está vazio.")

    # The same seed for every chunk keeps the voice consistent across the whole script
    seed = p['seed'] if p['seed'] >= 0 else random.randint(0, 2**31 - 1)
    rendered = []
    for i, chunk in enumerate(chunks, 1):
        if cancel_requested:
            return None
        eel.update_status(f"Clonando a voz com OmniVoice ({device_map}, {p['nfe_step']} passos) — trecho {i}/{len(chunks)}...")()
        torch.manual_seed(seed)
        audio = model.generate(
            text=chunk, ref_audio=ref_file, ref_text=ref_text,
            num_step=p['nfe_step'], speed=p['speed']
        )
        wav = _to_numpy_audio(audio[0])
        rendered.append(voice_utils.trim_edge_silence(wav, SAMPLE_RATE) if len(chunks) > 1 else wav)

    final = voice_utils.crossfade_concat(rendered, SAMPLE_RATE, ms=50)
    sf.write(output_path, final, SAMPLE_RATE, subtype='PCM_16')
    return seed

def clone_worker(options):
    """Worker executing voice cloning (F5-TTS or OmniVoice) in the background."""
    global cancel_requested
    ref_audio = options.get('refAudio')
    ref_text = options.get('refText')
    gen_text = options.get('genText')
    output_dir = options.get('outputDir')
    file_name = options.get('fileName', 'cloned_speech')

    if not ref_audio or not os.path.exists(ref_audio):
        eel.task_failed("Reference audio file does not exist.")()
        return

    if not ref_text:
        eel.task_failed("Reference text cannot be empty.")()
        return

    if not gen_text:
        eel.task_failed("Target text to synthesize cannot be empty.")()
        return

    if not output_dir or not os.path.exists(output_dir):
        # Default to user's Documents folder
        output_dir = os.path.join(os.path.expanduser('~'), 'Documents')
        os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, f"{file_name}.wav")

    def number(key, default, cast):
        try:
            return cast(options.get(key, default))
        except (TypeError, ValueError):
            return default

    engine = options.get('engine', 'f5')
    model_choice = options.get('modelChoice', 'pt')
    trim_ref = bool(options.get('trimRef', True))
    params = {
        'model_choice': model_choice,
        'language': options.get('language', 'pt'),
        'speed': number('speed', 1.0, float),
        'nfe_step': number('nfeStep', 32, int),
        'seed': number('seed', -1, int),
        'cfg_strength': number('cfgStrength', 2.0, float),
        'sway_coef': number('swayCoef', -1.0, float),
        'remove_silence': bool(options.get('removeSilence', False)),
    }
    # Language hint for Whisper when the reference has to be re-transcribed
    if engine == 'omnivoice':
        whisper_lang = params['language'] if params['language'] != 'other' else 'auto'
    else:
        whisper_lang = 'pt' if model_choice == 'pt' else 'auto'

    try:
        eel.update_status("Preparando áudio de referência...")()
        prepared = prepare_reference_audio(
            ref_audio, engine=engine, select_best=trim_ref,
            denoise=bool(options.get('removeNoise', True))
        )
        ref_file = prepared['path']
        eel.clone_warnings(prepared['warnings'])()

        # If the chosen passage excludes speech, the typed text no longer matches the audio:
        # transcribe the passage, unless the user already auto-transcribed this exact selection.
        key = _ref_cache_key(ref_audio, engine, trim_ref)
        if prepared['dropped_speech'] and key not in ref_transcript_cache:
            eel.update_status("Referência recortada: transcrevendo o trecho escolhido...")()
            new_text = _transcribe_audio(ref_file, whisper_lang)
            if new_text:
                ref_text = new_text
                ref_transcript_cache[key] = new_text
                eel.clone_ref_text_updated(new_text)()

        if cancel_requested:
            eel.task_cancelled()()
            return

        if engine == 'omnivoice':
            seed_used = _synthesize_omnivoice(ref_file, ref_text, gen_text, output_path, params)
        else:
            seed_used = _synthesize_f5(ref_file, ref_text, gen_text, output_path, params)

        if cancel_requested:
            eel.task_cancelled()()
            return

        if options.get('postProcess', True):
            eel.update_status("Pós-processando o áudio gerado...")()
            try:
                postprocess_output(output_path)
            except Exception as pp_err:
                print("Post-processing failed, keeping raw output:", pp_err)

        # Copy to web temp folder for playing in UI player
        web_temp_path = os.path.join(_web_temp_dir(), 'playback_clone.wav')
        try:
            shutil.copy(output_path, web_temp_path)
        except Exception as e:
            print("Error copying to temp playback:", e)

        done_msg = f"Voice cloned successfully as: {os.path.basename(output_path)}"
        if seed_used is not None:
            done_msg += f" (seed: {seed_used})"
        eel.task_completed(done_msg)()
        eel.clone_completed("temp/playback_clone.wav")()

    except Exception as e:
        import traceback
        traceback.print_exc()
        eel.task_failed(str(e))()

@eel.expose
def start_clone(options):
    """Starts the voice cloning background thread."""
    global active_thread, cancel_requested
    if active_thread and active_thread.is_alive():
        return "A task is already in progress."

    cancel_requested = False
    active_thread = threading.Thread(target=clone_worker, args=(options,))
    active_thread.start()
    return "Started"

if __name__ == '__main__':
    # Initialize eel
    eel.init('web')
    
    # Start app
    try:
        eel.start('index.html', port=0, size=(960, 780))
    except (SystemExit, KeyboardInterrupt):
        pass
    except Exception:
        # Fallback to default browser if chrome app mode isn't supported
        eel.start('index.html', port=0, mode='default', size=(960, 780))
