import os
import sys

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

import re
import threading
import subprocess
import shutil
import tkinter as tk
from tkinter import filedialog
import eel

# Global variables to control background tasks and handle cancellation
active_thread = None
cancel_requested = False
ffmpeg_process = None

def is_audio_file(file_path):
    """Checks if the file extension corresponds to a supported audio format."""
    ext = os.path.splitext(file_path)[1].lower()
    return ext in ['.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac', '.wma', '.webm']

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

            segments, info = model.transcribe(audio_path, **transcribe_args)
            total_duration = info.duration
            transcribed_segments = []
            
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

@eel.expose
def transcribe_reference(audio_path):
    """Transcribes a reference audio file using faster-whisper on GPU if available, or CPU."""
    if not audio_path or not os.path.exists(audio_path):
        return "Error: File does not exist."
        
    try:
        from faster_whisper import WhisperModel
        device = 'cuda' if len(dll_dirs) > 0 else 'cpu'
        compute_type = 'float16' if device == 'cuda' else 'int8'
        
        eel.update_status("Loading Whisper model for auto-transcription...")()
        # Use small model for fast reference audio transcription
        model = WhisperModel("small", device=device, compute_type=compute_type)
        
        eel.update_status("Transcribing reference audio...")()
        segments, info = model.transcribe(audio_path, beam_size=5)
        text = " ".join([seg.text.strip() for seg in segments])
        
        eel.update_status("Auto-transcription complete.")()
        return text
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Error transcribing reference audio: {str(e)}"

def clone_worker(options):
    """Worker executing F5-TTS voice cloning in the background."""
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
    
    # --- Text preprocessing for F5-TTS (critical for Portuguese model) ---
    # The pt-br model requires: lowercase text, numbers written as words
    def preprocess_text_for_f5tts(text, lang='pt_BR'):
        """Preprocesses text for F5-TTS inference.
        - Converts to lowercase (required by the pt-br model)
        - Converts numbers to their written-out form using num2words
        """
        try:
            from num2words import num2words
            def replace_number(match):
                num_str = match.group()
                try:
                    # Handle decimals
                    if '.' in num_str or ',' in num_str:
                        num_str_clean = num_str.replace('.', '').replace(',', '.')
                        return num2words(float(num_str_clean), lang=lang)
                    return num2words(int(num_str), lang=lang)
                except Exception:
                    return num_str
            # Replace numbers (including decimals with comma) with words
            text = re.sub(r'\d+([.,]\d+)?', replace_number, text)
        except ImportError:
            print("Warning: num2words not installed, skipping number conversion")
        
        # Fix common Portuguese num2words quirks
        text = text.replace(" e um mil", " e mil")
        text = text.replace("um mil ", "mil ")
        
        # Convert to lowercase (required by the model)
        text = text.lower()
        
        return text
        
    if not output_dir or not os.path.exists(output_dir):
        # Default to user's Documents folder
        output_dir = os.path.join(os.path.expanduser('~'), 'Documents')
        os.makedirs(output_dir, exist_ok=True)
        
    output_path = os.path.join(output_dir, f"{file_name}.wav")
    
    try:
        model_choice = options.get('modelChoice', 'pt')
        
        import torch
        from f5_tts.api import F5TTS
        
        if model_choice == 'pt':
            eel.update_status("Carregando modelo em Português (firstpixel/F5-TTS-pt-br)...")()
            from huggingface_hub import hf_hub_download
            ckpt_path = hf_hub_download(repo_id="firstpixel/F5-TTS-pt-br", filename="pt-br/model_last.safetensors")
            model_type = "F5TTS_Base"
        else:
            eel.update_status("Loading standard F5-TTS model (English/Chinese)...")()
            ckpt_path = ""
            model_type = "F5TTS_v1_Base"
            
        # Instantiate F5-TTS
        tts = F5TTS(
            model=model_type,
            ckpt_file=ckpt_path,
            device="cuda" if torch.cuda.is_available() else "cpu"
        )
        
        # Check if noise reduction is requested
        remove_noise = options.get('removeNoise', True)
        
        ref_file_to_use = ref_audio
        if remove_noise:
            try:
                eel.update_status("Removendo ruído de fundo do áudio de referência...")()
                import noisereduce as nr
                import soundfile as sf
                import numpy as np
                
                try:
                    data, rate = sf.read(ref_audio)
                except Exception:
                    from pydub import AudioSegment
                    audio = AudioSegment.from_file(ref_audio)
                    rate = audio.frame_rate
                    samples = np.array(audio.get_array_of_samples()).astype(np.float32)
                    if audio.sample_width == 2:
                        samples /= 32768.0
                    elif audio.sample_width == 4:
                        samples /= 2147483648.0
                    if audio.channels == 2:
                        samples = samples.reshape((-1, 2))
                    data = samples
                
                reduced_noise = nr.reduce_noise(y=data, sr=rate)
                
                temp_clean_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web', 'temp')
                os.makedirs(temp_clean_dir, exist_ok=True)
                ref_file_to_use = os.path.join(temp_clean_dir, 'cleaned_ref.wav')
                
                sf.write(ref_file_to_use, reduced_noise, rate)
                print("Noise reduction complete. Cleaned reference saved to:", ref_file_to_use)
            except Exception as nr_err:
                print("Failed to reduce noise:", nr_err)
                ref_file_to_use = ref_audio
        
        if cancel_requested:
            eel.task_cancelled()()
            return
            
        # Apply text preprocessing for Portuguese model
        if model_choice == 'pt':
            eel.update_status("Pré-processando texto para o modelo Português...")()
            ref_text = preprocess_text_for_f5tts(ref_text, lang='pt_BR')
            gen_text = preprocess_text_for_f5tts(gen_text, lang='pt_BR')
            print("Preprocessed ref_text:", ref_text[:200])
            print("Preprocessed gen_text:", gen_text[:200])
        
        eel.update_status("Clonando a voz com F5-TTS... (Processando na GPU)")()
        wav, sr, _ = tts.infer(
            ref_file=ref_file_to_use,
            ref_text=ref_text,
            gen_text=gen_text,
            file_wave=output_path
        )
        
        # Copy to web temp folder for playing in UI player
        web_temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web', 'temp')
        os.makedirs(web_temp_dir, exist_ok=True)
        web_temp_path = os.path.join(web_temp_dir, 'playback_clone.wav')
        try:
            shutil.copy(output_path, web_temp_path)
        except Exception as e:
            print("Error copying to temp playback:", e)
            
        eel.task_completed(f"Voice cloned successfully as: {os.path.basename(output_path)}")()
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
