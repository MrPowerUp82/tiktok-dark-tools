// --- Global State ---
let inputFile = null;
let outputDir = null;
let outputDirTts = null;
let outputDirClone = null;
let refAudioFile = null;
let isProcessing = false;
let segmentsText = [];
let activeTab = 'tab-transcription';

// --- DOM Elements ---
// Tab Buttons
const tabButtons = document.querySelectorAll('.tab-btn');
const tabs = document.querySelectorAll('.dashboard-grid');

// Tab 1 (Transcription) Elements
const btnSelectFile = document.getElementById('btn-select-file');
const btnSelectFolder = document.getElementById('btn-select-folder');
const displayInputFile = document.getElementById('display-input-file');
const displayOutputFolder = document.getElementById('display-output-folder');

const btnStart = document.getElementById('btn-start');
const btnCancel = document.getElementById('btn-cancel');
const btnOpenFolder = document.getElementById('btn-open-folder');
const btnCopy = document.getElementById('btn-copy');

const statusDot = document.getElementById('status-dot');
const statusMessage = document.getElementById('status-message');

const progressAudioContainer = document.getElementById('progress-audio-container');
const progressAudioFill = document.getElementById('progress-audio-fill');
const progressAudioPercent = document.getElementById('progress-audio-percent');

const progressTranscribeContainer = document.getElementById('progress-transcribe-container');
const progressTranscribeFill = document.getElementById('progress-transcribe-fill');
const progressTranscribePercent = document.getElementById('progress-transcribe-percent');

const transcriptDisplay = document.getElementById('transcript-display');
const transcriptPlaceholder = document.getElementById('transcript-placeholder');

// Tab 2 (TTS) Elements
const btnSelectFolderTts = document.getElementById('btn-select-folder-tts');
const displayOutputFolderTts = document.getElementById('display-output-folder-tts');
const ttsTextInput = document.getElementById('tts-text-input');
const ttsFilename = document.getElementById('tts-filename');
const ttsVoiceSelect = document.getElementById('tts-voice-select');
const ttsRateSlider = document.getElementById('tts-rate');
const ttsRateValue = document.getElementById('tts-rate-value');
const ttsPitchSlider = document.getElementById('tts-pitch');
const ttsPitchValue = document.getElementById('tts-pitch-value');

const btnStartTts = document.getElementById('btn-start-tts');
const btnCancelTts = document.getElementById('btn-cancel-tts');
const btnOpenFolderTts = document.getElementById('btn-open-folder-tts');

const statusDotTts = document.getElementById('status-dot-tts');
const statusMessageTts = document.getElementById('status-message-tts');

const playbackPlaceholder = document.getElementById('playback-placeholder');
const playerContainer = document.getElementById('player-container');
const ttsAudioPlayer = document.getElementById('tts-audio-player');

// Tab 3 (Voice Cloning) Elements
const btnSelectRefAudio = document.getElementById('btn-select-ref-audio');
const displayRefAudio = document.getElementById('display-ref-audio');
const btnSelectFolderClone = document.getElementById('btn-select-folder-clone');
const displayOutputFolderClone = document.getElementById('display-output-folder-clone');
const cloneFilename = document.getElementById('clone-filename');
const btnAutoTranscribe = document.getElementById('btn-auto-transcribe');
const cloneRefText = document.getElementById('clone-ref-text');
const cloneGenText = document.getElementById('clone-gen-text');
const cloneModelSelect = document.getElementById('clone-model-select');
const cloneTrimRef = document.getElementById('clone-trim-ref');
const cloneRemoveSilence = document.getElementById('clone-remove-silence');
const cloneNfeSelect = document.getElementById('clone-nfe');
const cloneSeedInput = document.getElementById('clone-seed');
const cloneSpeedSlider = document.getElementById('clone-speed');
const cloneSpeedValue = document.getElementById('clone-speed-value');

const btnStartClone = document.getElementById('btn-start-clone');
const btnCancelClone = document.getElementById('btn-cancel-clone');
const btnOpenFolderClone = document.getElementById('btn-open-folder-clone');

const statusDotClone = document.getElementById('status-dot-clone');
const statusMessageClone = document.getElementById('status-message-clone');

const playbackPlaceholderClone = document.getElementById('playback-placeholder-clone');
const playerContainerClone = document.getElementById('player-container-clone');
const cloneAudioPlayer = document.getElementById('clone-audio-player');

// --- Helper Functions ---
function getBasename(path) {
    return path.split(/[/\\]/).pop();
}

function formatSeconds(secs) {
    const mm = Math.floor(secs / 60).toString().padStart(2, '0');
    const ss = Math.floor(secs % 60).toString().padStart(2, '0');
    return `${mm}:${ss}`;
}

// Disable/Enable input controls based on active status
function setControlsDisabled(disabled) {
    isProcessing = disabled;
    
    // Lock/Unlock tabs
    tabButtons.forEach(btn => btn.disabled = disabled);

    // Disable Tab 1 Controls
    btnSelectFile.disabled = disabled;
    btnSelectFolder.disabled = disabled;
    const radios = document.querySelectorAll('input[name="action-mode"]');
    radios.forEach(r => r.disabled = disabled);
    document.getElementById('whisper-model').disabled = disabled;
    document.getElementById('language-select').disabled = disabled;
    document.getElementById('device-select').disabled = disabled;
    document.getElementById('compute-type').disabled = disabled;
    document.getElementById('audio-format').disabled = disabled;
    document.getElementById('export-txt').disabled = disabled;
    document.getElementById('export-srt').disabled = disabled;
    document.getElementById('export-vtt').disabled = disabled;
    document.getElementById('export-tiktok').disabled = disabled;
    document.getElementById('tiktok-max-words').disabled = disabled;
    document.getElementById('tiktok-max-duration').disabled = disabled;
    
    if (disabled) {
        btnStart.classList.add('hidden');
        btnCancel.classList.remove('hidden');
    } else {
        btnStart.classList.remove('hidden');
        btnCancel.classList.add('hidden');
    }

    // Disable Tab 2 Controls
    btnSelectFolderTts.disabled = disabled;
    ttsTextInput.disabled = disabled;
    ttsFilename.disabled = disabled;
    ttsVoiceSelect.disabled = disabled;
    ttsRateSlider.disabled = disabled;
    ttsPitchSlider.disabled = disabled;

    if (disabled) {
        btnStartTts.classList.add('hidden');
        btnCancelTts.classList.remove('hidden');
    } else {
        btnStartTts.classList.remove('hidden');
        btnCancelTts.classList.add('hidden');
    }

    // Disable Tab 3 Controls
    btnSelectRefAudio.disabled = disabled;
    btnSelectFolderClone.disabled = disabled;
    cloneFilename.disabled = disabled;
    btnAutoTranscribe.disabled = disabled;
    cloneRefText.disabled = disabled;
    cloneGenText.disabled = disabled;
    cloneModelSelect.disabled = disabled;
    document.getElementById('clone-remove-noise').disabled = disabled;
    cloneTrimRef.disabled = disabled;
    cloneRemoveSilence.disabled = disabled;
    cloneNfeSelect.disabled = disabled;
    cloneSeedInput.disabled = disabled;
    cloneSpeedSlider.disabled = disabled;

    if (disabled) {
        btnStartClone.classList.add('hidden');
        btnCancelClone.classList.remove('hidden');
    } else {
        btnStartClone.classList.remove('hidden');
        btnCancelClone.classList.add('hidden');
    }
}

// Toggle options view depending on which mode is selected (Tab 1)
function updateModeUI() {
    const mode = document.querySelector('input[name="action-mode"]:checked').value;
    const audioSettings = document.getElementById('audio-settings-container');
    const textSettings = document.querySelectorAll('.text-settings');
    
    if (mode === 'audio') {
        audioSettings.classList.remove('hidden');
        textSettings.forEach(el => el.classList.add('hidden'));
    } else if (mode === 'transcribe') {
        audioSettings.classList.add('hidden');
        textSettings.forEach(el => el.classList.remove('hidden'));
    } else if (mode === 'both') {
        audioSettings.classList.remove('hidden');
        textSettings.forEach(el => el.classList.remove('hidden'));
    }
}

// Load and populate available voices in dropdown (Tab 2)
async function loadVoices() {
    try {
        ttsVoiceSelect.innerHTML = '<option value="" disabled selected>Loading voices list...</option>';
        const voices = await eel.get_voices()();
        ttsVoiceSelect.innerHTML = '';
        
        if (!voices || voices.length === 0) {
            ttsVoiceSelect.innerHTML = '<option value="pt-BR-FranciscaNeural">pt-BR - Francisca (Female)</option>';
            return;
        }

        // Sort by locale (language) first, then gender
        voices.sort((a, b) => {
            if (a.locale !== b.locale) return a.locale.localeCompare(b.locale);
            return a.gender.localeCompare(b.gender);
        });

        let defaultIndex = 0;
        voices.forEach((v, index) => {
            const opt = document.createElement('option');
            opt.value = v.shortName;
            opt.textContent = v.friendlyName;
            ttsVoiceSelect.appendChild(opt);

            // Default to pt-BR Francisca voice
            if (v.shortName === 'pt-BR-FranciscaNeural') {
                defaultIndex = index;
            }
        });

        ttsVoiceSelect.selectedIndex = defaultIndex;
    } catch (err) {
        console.error("Failed to load voices:", err);
        ttsVoiceSelect.innerHTML = '<option value="pt-BR-FranciscaNeural">pt-BR - Francisca (Female) [Fallback]</option>';
    }
}

// Format rate value slider label (+/- X%)
function formatRateLabel(value) {
    if (value === 0) return "Normal (1.0x)";
    const prefix = value > 0 ? "+" : "";
    return `${prefix}${value}%`;
}

// Format pitch value slider label (+/- XHz)
function formatPitchLabel(value) {
    if (value === 0) return "Normal (0Hz)";
    const prefix = value > 0 ? "+" : "";
    return `${prefix}${value}Hz`;
}

// --- Event Listeners ---

// Tab switching logic
tabButtons.forEach(button => {
    button.addEventListener('click', () => {
        if (isProcessing) return; // Do not switch while running
        
        const targetTab = button.getAttribute('data-tab');
        
        tabButtons.forEach(btn => btn.classList.remove('active'));
        tabs.forEach(tab => tab.classList.remove('active-tab'));
        
        button.classList.add('active');
        document.getElementById(targetTab).classList.add('active-tab');
        activeTab = targetTab;
    });
});

// Slider inputs value labels binding (Tab 2)
ttsRateSlider.addEventListener('input', (e) => {
    ttsRateValue.textContent = formatRateLabel(parseInt(e.target.value));
});

ttsPitchSlider.addEventListener('input', (e) => {
    ttsPitchValue.textContent = formatPitchLabel(parseInt(e.target.value));
});

// Clone speech speed slider label (Tab 3)
cloneSpeedSlider.addEventListener('input', (e) => {
    const speed = parseInt(e.target.value) / 100;
    cloneSpeedValue.textContent = speed === 1 ? "Normal (1.0x)" : `${speed.toFixed(2)}x`;
});

// Watch radio buttons mode change (Tab 1)
document.querySelectorAll('input[name="action-mode"]').forEach(radio => {
    radio.addEventListener('change', updateModeUI);
});

// Toggle TikTok style options
const exportTiktok = document.getElementById('export-tiktok');
const tiktokOptions = document.getElementById('tiktok-options');
exportTiktok.addEventListener('change', () => {
    if (exportTiktok.checked) {
        tiktokOptions.classList.remove('hidden');
    } else {
        tiktokOptions.classList.add('hidden');
    }
});

// Select input file (Tab 1)
btnSelectFile.addEventListener('click', async () => {
    if (isProcessing) return;
    try {
        const path = await eel.select_file()();
        if (path) {
            inputFile = path;
            displayInputFile.textContent = getBasename(path);
            displayInputFile.title = path;
            displayInputFile.style.color = 'var(--text-primary)';
            
            // Auto-fill output folder if empty
            if (!outputDir) {
                const defaultDir = path.substring(0, Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\')));
                displayOutputFolder.textContent = defaultDir;
                displayOutputFolder.title = defaultDir;
                displayOutputFolder.style.color = 'var(--text-secondary)';
            }
        }
    } catch (err) {
        console.error("Failed to select file:", err);
    }
});

// Select output folder (Tab 1)
btnSelectFolder.addEventListener('click', async () => {
    if (isProcessing) return;
    try {
        const path = await eel.select_folder()();
        if (path) {
            outputDir = path;
            displayOutputFolder.textContent = path;
            displayOutputFolder.title = path;
            displayOutputFolder.style.color = 'var(--text-primary)';
        }
    } catch (err) {
        console.error("Failed to select folder:", err);
    }
});

// Select output folder (Tab 2)
btnSelectFolderTts.addEventListener('click', async () => {
    if (isProcessing) return;
    try {
        const path = await eel.select_folder()();
        if (path) {
            outputDirTts = path;
            displayOutputFolderTts.textContent = path;
            displayOutputFolderTts.title = path;
            displayOutputFolderTts.style.color = 'var(--text-primary)';
        }
    } catch (err) {
        console.error("Failed to select folder for TTS:", err);
    }
});

// Select reference audio (Tab 3)
btnSelectRefAudio.addEventListener('click', async () => {
    if (isProcessing) return;
    try {
        const path = await eel.select_file()();
        if (path) {
            refAudioFile = path;
            displayRefAudio.textContent = getBasename(path);
            displayRefAudio.title = path;
            displayRefAudio.style.color = 'var(--text-primary)';
        }
    } catch (err) {
        console.error("Failed to select reference audio:", err);
    }
});

// Select output folder (Tab 3)
btnSelectFolderClone.addEventListener('click', async () => {
    if (isProcessing) return;
    try {
        const path = await eel.select_folder()();
        if (path) {
            outputDirClone = path;
            displayOutputFolderClone.textContent = path;
            displayOutputFolderClone.title = path;
            displayOutputFolderClone.style.color = 'var(--text-primary)';
        }
    } catch (err) {
        console.error("Failed to select folder for voice cloning:", err);
    }
});

// Auto-Transcribe Reference Audio (Tab 3)
btnAutoTranscribe.addEventListener('click', async () => {
    if (isProcessing) return;
    
    if (!refAudioFile) {
        alert("Please select a reference audio file first.");
        return;
    }
    
    btnAutoTranscribe.disabled = true;
    btnAutoTranscribe.textContent = 'Transcribing...';
    updateStatusDot('active');
    
    try {
        // Hint whisper with the language of the selected model, and transcribe the
        // exact same (trimmed) audio the cloning step will consume
        const language = cloneModelSelect.value === 'pt' ? 'pt' : 'auto';
        const transcription = await eel.transcribe_reference(refAudioFile, language, cloneTrimRef.checked)();
        if (transcription.startsWith("Error")) {
            alert(transcription);
            updateStatusDot('error');
        } else {
            cloneRefText.value = transcription;
            updateStatusDot('success');
        }
    } catch (err) {
        console.error("Failed auto-transcription:", err);
        alert("Transcription failed: " + err);
        updateStatusDot('error');
    } finally {
        btnAutoTranscribe.disabled = false;
        btnAutoTranscribe.textContent = 'Auto-Transcribe';
    }
});

// Start button (Tab 1 - Transcribe)
btnStart.addEventListener('click', async () => {
    if (isProcessing) return;
    
    if (!inputFile) {
        alert("Please select a media input file first.");
        return;
    }
    
    const mode = document.querySelector('input[name="action-mode"]:checked').value;
    
    let exportFormats = [];
    if (mode === 'transcribe' || mode === 'both') {
        if (document.getElementById('export-txt').checked) exportFormats.push('txt');
        if (document.getElementById('export-srt').checked) exportFormats.push('srt');
        if (document.getElementById('export-vtt').checked) exportFormats.push('vtt');
        
        if (exportFormats.length === 0) {
            alert("Please check at least one transcript export format (.txt, .srt, or .vtt).");
            return;
        }
    }
    
    segmentsText = [];
    transcriptDisplay.innerHTML = '';
    btnCopy.disabled = true;
    btnOpenFolder.classList.add('hidden');
    
    progressAudioFill.style.width = '0%';
    progressAudioPercent.textContent = '0%';
    progressAudioContainer.classList.add('hidden');
    
    progressTranscribeFill.style.width = '0%';
    progressTranscribePercent.textContent = '0%';
    progressTranscribeContainer.classList.add('hidden');
    
    setControlsDisabled(true);
    updateStatusDot('active');
    
    const options = {
        inputFile: inputFile,
        outputDir: outputDir,
        action: mode,
        audioFormat: document.getElementById('audio-format').value,
        modelSize: document.getElementById('whisper-model').value,
        language: document.getElementById('language-select').value,
        device: document.getElementById('device-select').value,
        computeType: document.getElementById('compute-type').value,
        exportFormats: exportFormats,
        tiktokStyle: document.getElementById('export-tiktok').checked,
        tiktokMaxWords: parseInt(document.getElementById('tiktok-max-words').value) || 3,
        tiktokMaxDuration: parseFloat(document.getElementById('tiktok-max-duration').value) || 1.5
    };
    
    try {
        const response = await eel.start_process(options)();
        if (response !== "Started") {
            alert(response);
            setControlsDisabled(false);
            updateStatusDot('idle');
            statusMessage.textContent = response;
        }
    } catch (err) {
        console.error("Error executing task:", err);
        setControlsDisabled(false);
        updateStatusDot('error');
        statusMessage.textContent = "Error: " + err;
    }
});

// Start button (Tab 2 - TTS)
btnStartTts.addEventListener('click', async () => {
    if (isProcessing) return;
    
    const text = ttsTextInput.value.trim();
    if (!text) {
        alert("Please type or paste some text to generate speech.");
        return;
    }
    
    const filename = ttsFilename.value.trim();
    if (!filename) {
        alert("Please enter an output filename.");
        return;
    }
    
    // Hide player controls, show placeholder
    playerContainer.classList.add('hidden');
    playbackPlaceholder.classList.remove('hidden');
    btnOpenFolderTts.classList.add('hidden');
    ttsAudioPlayer.pause();
    
    setControlsDisabled(true);
    updateStatusDot('active');
    
    const rateVal = parseInt(ttsRateSlider.value);
    const rateString = `${rateVal >= 0 ? '+' : ''}${rateVal}%`;
    
    const pitchVal = parseInt(ttsPitchSlider.value);
    const pitchString = `${pitchVal >= 0 ? '+' : ''}${pitchVal}Hz`;
    
    const options = {
        text: text,
        voice: ttsVoiceSelect.value,
        outputDir: outputDirTts,
        fileName: filename,
        rate: rateString,
        pitch: pitchString
    };
    
    try {
        const response = await eel.generate_tts(options)();
        if (response !== "Started") {
            alert(response);
            setControlsDisabled(false);
            updateStatusDot('idle');
            statusMessageTts.textContent = response;
        }
    } catch (err) {
        console.error("Error executing TTS task:", err);
        setControlsDisabled(false);
        updateStatusDot('error');
        statusMessageTts.textContent = "Error: " + err;
    }
});

// Start button (Tab 3 - Voice Cloning F5-TTS)
btnStartClone.addEventListener('click', async () => {
    if (isProcessing) return;
    
    if (!refAudioFile) {
        alert("Please select a reference audio file first.");
        return;
    }
    
    const refText = cloneRefText.value.trim();
    if (!refText) {
        alert("Please enter the transcription text for the reference audio.");
        return;
    }
    
    const genText = cloneGenText.value.trim();
    if (!genText) {
        alert("Please enter the target script you want to synthesize.");
        return;
    }
    
    const filename = cloneFilename.value.trim();
    if (!filename) {
        alert("Please enter an output filename.");
        return;
    }
    
    // Hide player controls, show placeholder
    playerContainerClone.classList.add('hidden');
    playbackPlaceholderClone.classList.remove('hidden');
    btnOpenFolderClone.classList.add('hidden');
    cloneAudioPlayer.pause();
    
    setControlsDisabled(true);
    updateStatusDot('active');
    
    let seed = parseInt(cloneSeedInput.value);
    if (isNaN(seed)) seed = -1;

    const options = {
        refAudio: refAudioFile,
        refText: refText,
        genText: genText,
        outputDir: outputDirClone,
        fileName: filename,
        modelChoice: cloneModelSelect.value,
        removeNoise: document.getElementById('clone-remove-noise').checked,
        trimRef: cloneTrimRef.checked,
        removeSilence: cloneRemoveSilence.checked,
        nfeStep: parseInt(cloneNfeSelect.value),
        seed: seed,
        speed: parseInt(cloneSpeedSlider.value) / 100
    };
    
    try {
        const response = await eel.start_clone(options)();
        if (response !== "Started") {
            alert(response);
            setControlsDisabled(false);
            updateStatusDot('idle');
            statusMessageClone.textContent = response;
        }
    } catch (err) {
        console.error("Error executing Voice Cloning task:", err);
        setControlsDisabled(false);
        updateStatusDot('error');
        statusMessageClone.textContent = "Error: " + err;
    }
});

// Cancel buttons
btnCancel.addEventListener('click', async () => {
    if (!isProcessing) return;
    statusMessage.textContent = "Requesting cancel...";
    btnCancel.disabled = true;
    try {
        await eel.cancel_task()();
    } catch (err) {
        console.error("Failed to cancel transcription task:", err);
    }
});

btnCancelTts.addEventListener('click', async () => {
    if (!isProcessing) return;
    statusMessageTts.textContent = "Requesting cancel...";
    btnCancelTts.disabled = true;
    try {
        await eel.cancel_task()();
    } catch (err) {
        console.error("Failed to cancel TTS task:", err);
    }
});

btnCancelClone.addEventListener('click', async () => {
    if (!isProcessing) return;
    statusMessageClone.textContent = "Requesting cancel...";
    btnCancelClone.disabled = true;
    try {
        await eel.cancel_task()();
    } catch (err) {
        console.error("Failed to cancel Voice Cloning task:", err);
    }
});

// Copy transcript
btnCopy.addEventListener('click', () => {
    if (segmentsText.length === 0) return;
    const textToCopy = segmentsText.join('\n');
    navigator.clipboard.writeText(textToCopy).then(() => {
        const originalText = btnCopy.textContent;
        btnCopy.textContent = 'Copied!';
        btnCopy.style.borderColor = 'var(--color-success)';
        btnCopy.style.color = 'var(--color-success)';
        setTimeout(() => {
            btnCopy.textContent = originalText;
            btnCopy.style.borderColor = '';
            btnCopy.style.color = '';
        }, 2000);
    });
});

// Open directories buttons
btnOpenFolder.addEventListener('click', async () => {
    const targetDir = outputDir || inputFile.substring(0, Math.max(inputFile.lastIndexOf('/'), inputFile.lastIndexOf('\\')));
    try {
        await eel.open_output_dir(targetDir)();
    } catch (err) {
        console.error("Failed to open output directory:", err);
    }
});

btnOpenFolderTts.addEventListener('click', async () => {
    const targetDir = outputDirTts || "";
    try {
        await eel.open_output_dir(targetDir)();
    } catch (err) {
        console.error("Failed to open TTS directory:", err);
    }
});

btnOpenFolderClone.addEventListener('click', async () => {
    const targetDir = outputDirClone || "";
    try {
        await eel.open_output_dir(targetDir)();
    } catch (err) {
        console.error("Failed to open Clone directory:", err);
    }
});

// Helper to update visual pulse dot in active tab
function updateStatusDot(state) {
    if (activeTab === 'tab-transcription') {
        statusDot.className = 'pulse-dot ' + state;
    } else if (activeTab === 'tab-tts') {
        statusDotTts.className = 'pulse-dot ' + state;
    } else if (activeTab === 'tab-clone') {
        statusDotClone.className = 'pulse-dot ' + state;
    }
}

// --- Exposed Eel Callback Functions (Called by Python) ---

eel.expose(update_status);
function update_status(message) {
    if (activeTab === 'tab-transcription') {
        statusMessage.textContent = message;
    } else if (activeTab === 'tab-tts') {
        statusMessageTts.textContent = message;
    } else if (activeTab === 'tab-clone') {
        statusMessageClone.textContent = message;
    }
    console.log("[Status]:", message);
}

eel.expose(update_progress);
function update_progress(phase, progress, message) {
    if (phase === 'audio') {
        progressAudioContainer.classList.remove('hidden');
        progressAudioFill.style.width = `${progress}%`;
        progressAudioPercent.textContent = `${progress}%`;
    } else if (phase === 'transcribe') {
        progressTranscribeContainer.classList.remove('hidden');
        progressTranscribeFill.style.width = `${progress}%`;
        progressTranscribePercent.textContent = `${progress}%`;
    }
    statusMessage.textContent = message;
}

eel.expose(new_segment);
function new_segment(segment) {
    if (transcriptPlaceholder) {
        transcriptPlaceholder.remove();
    }
    
    const segDiv = document.createElement('div');
    segDiv.className = 'transcript-segment';
    
    const timeSpan = document.createElement('span');
    timeSpan.className = 'segment-time';
    timeSpan.textContent = `[${formatSeconds(segment.start)} → ${formatSeconds(segment.end)}]`;
    
    const textSpan = document.createElement('span');
    textSpan.className = 'segment-text';
    textSpan.textContent = segment.text;
    
    segDiv.appendChild(timeSpan);
    segDiv.appendChild(textSpan);
    
    transcriptDisplay.appendChild(segDiv);
    transcriptDisplay.scrollTop = transcriptDisplay.scrollHeight;
    
    segmentsText.push(`[${formatSeconds(segment.start)} -> ${formatSeconds(segment.end)}] ${segment.text.trim()}`);
}

eel.expose(task_completed);
function task_completed(message) {
    setControlsDisabled(false);
    updateStatusDot('success');
    
    if (activeTab === 'tab-transcription') {
        statusMessage.textContent = message;
        btnOpenFolder.classList.remove('hidden');
        if (segmentsText.length > 0) {
            btnCopy.disabled = false;
        }
    } else if (activeTab === 'tab-tts') {
        statusMessageTts.textContent = message;
        btnOpenFolderTts.classList.remove('hidden');
    } else if (activeTab === 'tab-clone') {
        statusMessageClone.textContent = message;
        btnOpenFolderClone.classList.remove('hidden');
    }
    
    btnCancel.disabled = false;
    btnCancelTts.disabled = false;
    btnCancelClone.disabled = false;
}

eel.expose(task_failed);
function task_failed(errorMessage) {
    setControlsDisabled(false);
    updateStatusDot('error');
    
    if (activeTab === 'tab-transcription') {
        statusMessage.textContent = "Failed: " + errorMessage;
    } else if (activeTab === 'tab-tts') {
        statusMessageTts.textContent = "Failed: " + errorMessage;
    } else if (activeTab === 'tab-clone') {
        statusMessageClone.textContent = "Failed: " + errorMessage;
    }
    
    btnCancel.disabled = false;
    btnCancelTts.disabled = false;
    btnCancelClone.disabled = false;
}

eel.expose(task_cancelled);
function task_cancelled() {
    setControlsDisabled(false);
    updateStatusDot('idle');
    
    if (activeTab === 'tab-transcription') {
        statusMessage.textContent = "Task cancelled by user.";
    } else if (activeTab === 'tab-tts') {
        statusMessageTts.textContent = "Task cancelled by user.";
    } else if (activeTab === 'tab-clone') {
        statusMessageClone.textContent = "Task cancelled by user.";
    }
    
    btnCancel.disabled = false;
    btnCancelTts.disabled = false;
    btnCancelClone.disabled = false;
}

// Exposed callback specifically for Text-to-Speech completion
eel.expose(tts_completed);
function tts_completed(tempFilePath) {
    playbackPlaceholder.classList.add('hidden');
    playerContainer.classList.remove('hidden');
    
    ttsAudioPlayer.src = `${tempFilePath}?t=${Date.now()}`;
    ttsAudioPlayer.classList.remove('hidden');
    ttsAudioPlayer.load();
    
    ttsAudioPlayer.play().catch(err => {
        console.warn("Audio autoplay blocked by browser policy:", err);
    });
}

// Exposed callback specifically for Voice Cloning completion
eel.expose(clone_completed);
function clone_completed(tempFilePath) {
    playbackPlaceholderClone.classList.add('hidden');
    playerContainerClone.classList.remove('hidden');
    
    cloneAudioPlayer.src = `${tempFilePath}?t=${Date.now()}`;
    cloneAudioPlayer.classList.remove('hidden');
    cloneAudioPlayer.load();
    
    cloneAudioPlayer.play().catch(err => {
        console.warn("Audio autoplay blocked by browser policy:", err);
    });
}

// Initial UI triggers
updateModeUI();
loadVoices();
console.log("VoiceFlow UI and tabs loaded successfully.");
