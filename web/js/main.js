// --- Global State ---
let inputFile = null;
let outputDir = null;
let isProcessing = false;
let segmentsText = [];

// --- DOM Elements ---
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
    
    // Disable inputs
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
    
    if (disabled) {
        btnStart.classList.add('hidden');
        btnCancel.classList.remove('hidden');
    } else {
        btnStart.classList.remove('hidden');
        btnCancel.classList.add('hidden');
    }
}

// Toggle options view depending on which mode is selected
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

// --- Event Listeners ---

// Watch radio buttons mode change
document.querySelectorAll('input[name="action-mode"]').forEach(radio => {
    radio.addEventListener('change', updateModeUI);
});

// Select file button click handler
btnSelectFile.addEventListener('click', async () => {
    if (isProcessing) return;
    try {
        const path = await eel.select_file()();
        if (path) {
            inputFile = path;
            displayInputFile.textContent = getBasename(path);
            displayInputFile.title = path;
            displayInputFile.style.color = 'var(--text-primary)';
            
            // Set output folder defaults if not selected yet
            if (!outputDir) {
                // Remove filename to show output directory placeholder
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

// Select folder button click handler
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

// Start button click handler
btnStart.addEventListener('click', async () => {
    if (isProcessing) return;
    
    if (!inputFile) {
        alert("Please select a media input file first.");
        return;
    }
    
    const mode = document.querySelector('input[name="action-mode"]:checked').value;
    
    // Validate export checkboxes if transcription is selected
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
    
    // Clear displays and transcripts
    segmentsText = [];
    transcriptDisplay.innerHTML = '';
    btnCopy.disabled = true;
    btnOpenFolder.classList.add('hidden');
    
    // Reset progress fill values
    progressAudioFill.style.width = '0%';
    progressAudioPercent.textContent = '0%';
    progressAudioContainer.classList.add('hidden');
    
    progressTranscribeFill.style.width = '0%';
    progressTranscribePercent.textContent = '0%';
    progressTranscribeContainer.classList.add('hidden');
    
    // Update active UI status
    setControlsDisabled(true);
    updateStatusDot('active');
    
    // Build options payload
    const options = {
        inputFile: inputFile,
        outputDir: outputDir, // Will default to file dir in backend if empty
        action: mode,
        audioFormat: document.getElementById('audio-format').value,
        modelSize: document.getElementById('whisper-model').value,
        language: document.getElementById('language-select').value,
        device: document.getElementById('device-select').value,
        computeType: document.getElementById('compute-type').value,
        exportFormats: exportFormats
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
        console.error("Error executing processing task:", err);
        setControlsDisabled(false);
        updateStatusDot('error');
        statusMessage.textContent = "Error: " + err;
    }
});

// Cancel button click handler
btnCancel.addEventListener('click', async () => {
    if (!isProcessing) return;
    statusMessage.textContent = "Requesting cancel...";
    btnCancel.disabled = true;
    try {
        await eel.cancel_task()();
    } catch (err) {
        console.error("Failed to cancel task:", err);
    }
});

// Copy to clipboard click handler
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
    }).catch(err => {
        console.error('Could not copy text to clipboard: ', err);
    });
});

// Open Folder button click handler
btnOpenFolder.addEventListener('click', async () => {
    // If outputDir is null, use parent dir of inputFile
    const targetDir = outputDir || inputFile.substring(0, Math.max(inputFile.lastIndexOf('/'), inputFile.lastIndexOf('\\')));
    try {
        await eel.open_output_dir(targetDir)();
    } catch (err) {
        console.error("Failed to open directory:", err);
    }
});

// Status helper to change pulse color
function updateStatusDot(state) {
    statusDot.className = 'pulse-dot';
    statusDot.classList.add(state);
}

// --- Exposed Eel Callback Functions (Called by Python) ---

eel.expose(update_status);
function update_status(message) {
    statusMessage.textContent = message;
    console.log("[Status Update]:", message);
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
    // Remove placeholder on first segment
    if (transcriptPlaceholder) {
        transcriptPlaceholder.remove();
    }
    
    // Create segment card element
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
    
    // Auto-scroll scroll container
    transcriptDisplay.scrollTop = transcriptDisplay.scrollHeight;
    
    // Save to copy cache
    segmentsText.push(`[${formatSeconds(segment.start)} -> ${formatSeconds(segment.end)}] ${segment.text.trim()}`);
}

eel.expose(task_completed);
function task_completed(message) {
    setControlsDisabled(false);
    updateStatusDot('success');
    statusMessage.textContent = message;
    btnCancel.disabled = false;
    
    // Enable post-process actions
    if (segmentsText.length > 0) {
        btnCopy.disabled = false;
    }
    btnOpenFolder.classList.remove('hidden');
}

eel.expose(task_failed);
function task_failed(errorMessage) {
    setControlsDisabled(false);
    updateStatusDot('error');
    statusMessage.textContent = "Failed: " + errorMessage;
    btnCancel.disabled = false;
    btnOpenFolder.classList.add('hidden');
}

eel.expose(task_cancelled);
function task_cancelled() {
    setControlsDisabled(false);
    updateStatusDot('idle');
    statusMessage.textContent = "Task cancelled by user.";
    btnCancel.disabled = false;
    btnOpenFolder.classList.add('hidden');
}

// Initial UI triggers
updateModeUI();
console.log("VoiceFlow UI initialized successfully.");
