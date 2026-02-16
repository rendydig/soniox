import { WebSocketManager } from './websocket-manager.js';
import { PracticeModeManager } from './practice-mode.js';
import { SubtitleManager } from './subtitle-manager.js';
import { PlaylistManager } from './playlist-manager.js';
import { AudioControlsManager } from './audio-controls-manager.js';
import { RepeatLoopManager } from './repeat-loop-manager.js';

class MP3Player {
    constructor() {
        this.audioPlayer = document.getElementById('audioPlayer');
        this.currentTrackEl = document.getElementById('currentTrack');
        this.trackDetailsEl = document.getElementById('trackDetails');
        this.refreshBtn = document.getElementById('refreshBtn');
        this.micToggleBtn = document.getElementById('micToggleBtn');
        this.clearRecognitionBtn = document.getElementById('clearRecognitionBtn');
        this.recognitionLanguageSelector = document.getElementById('recognitionLanguage');
        
        this.practiceMode = false;
        this.recognition = null;
        this.recognitionText = '';
        this.isRecognizing = false;
        this.recognitionRestartTimeout = null;
        this.practicePanel = document.getElementById('practicePanel');
        this.practiceStatus = document.getElementById('practiceStatus');
        this.recognitionTextEl = document.getElementById('recognitionText');
        this.currentPracticeLineIndex = -1;
        this.lastSpeechTime = null;
        this.silenceCheckInterval = null;
        this.pendingSpeechText = '';
        
        this.subtitleManager = new SubtitleManager(this);
        this.playlistManager = new PlaylistManager(this);
        this.audioControlsManager = new AudioControlsManager(this);
        this.repeatLoopManager = new RepeatLoopManager(this);
        this.practiceModeManager = new PracticeModeManager(this);
        this.practiceModeManager.initSpeechRecognition();
        
        this.initWebSocket();
        this.initEventListeners();
    }


    initWebSocket() {
        this.wsManager = new WebSocketManager(
            (connected) => this.updateConnectionStatus(connected),
            (data) => this.handleWebSocketMessage(data)
        );
        this.wsManager.connect();
    }

    updateConnectionStatus(connected) {
        const statusIndicator = document.getElementById('statusIndicator');
        const statusText = document.getElementById('statusText');
        
        if (connected) {
            statusIndicator.className = 'status-indicator connected';
            statusText.textContent = 'Connected';
            this.playlistManager.requestTracks(this.wsManager);
        } else {
            statusIndicator.className = 'status-indicator disconnected';
            statusText.textContent = 'Disconnected';
        }
    }

    handleWebSocketMessage(data) {
        if (data.type === 'mp3_list') {
            this.playlistManager.setTracks(data.tracks);
        } else if (data.type === 'connection') {
            this.playlistManager.requestTracks(this.wsManager);
        }
    }


    async loadTrack(index) {
        const tracks = this.playlistManager.getTracks();
        if (index < 0 || index >= tracks.length) return;
        
        this.playlistManager.setCurrentIndex(index);
        const track = tracks[index];
        
        this.audioPlayer.src = track.url;
        this.audioPlayer.load();
        
        this.currentTrackEl.textContent = track.name;
        this.trackDetailsEl.textContent = `Track ${index + 1} of ${tracks.length}`;
        
        await this.subtitleManager.loadSubtitles(track.srtUrl, track.srtRomajiUrl, track.srtEnUrl, track.srtIdUrl);
        
        this.playlistManager.renderPlaylist();
        this.practiceModeManager.updateMicButtonState();
    }

    async playTrack(index) {
        const tracks = this.playlistManager.getTracks();
        if (index < 0 || index >= tracks.length) return;
        
        this.playlistManager.setCurrentIndex(index);
        const track = tracks[index];
        
        this.audioPlayer.src = track.url;
        this.audioPlayer.load();
        this.audioPlayer.play();
        
        this.currentTrackEl.textContent = track.name;
        this.trackDetailsEl.textContent = `Track ${index + 1} of ${tracks.length}`;
        
        await this.subtitleManager.loadSubtitles(track.srtUrl, track.srtRomajiUrl, track.srtEnUrl, track.srtIdUrl);
        
        this.playlistManager.renderPlaylist();
        this.practiceModeManager.updateMicButtonState();
    }


    initEventListeners() {
        this.audioControlsManager.playPauseBtn.addEventListener('click', () => this.audioControlsManager.togglePlayPause());
        this.audioControlsManager.nextBtn.addEventListener('click', () => this.audioControlsManager.playNext());
        this.audioControlsManager.prevBtn.addEventListener('click', () => this.audioControlsManager.playPrevious());
        this.audioControlsManager.repeatBtn.addEventListener('click', () => this.audioControlsManager.toggleRepeat());
        this.refreshBtn.addEventListener('click', () => this.playlistManager.requestTracks(this.wsManager));
        
        this.audioControlsManager.progressBar.addEventListener('input', (e) => this.audioControlsManager.seekTo(e));
        this.audioControlsManager.volumeSlider.addEventListener('input', () => this.audioControlsManager.updateVolume());
        this.audioControlsManager.speedSlider.addEventListener('change', () => this.audioControlsManager.updateSpeed());
        this.subtitleManager.translationLanguageSelector.addEventListener('change', () => this.subtitleManager.switchTranslationLanguage());
        this.subtitleManager.showSubtitleCheckbox.addEventListener('change', () => this.subtitleManager.toggleSubtitleVisibility());
        this.subtitleManager.showRomajiCheckbox.addEventListener('change', () => this.subtitleManager.toggleSubtitleVisibility());
        this.subtitleManager.showTranslationCheckbox.addEventListener('change', () => this.subtitleManager.toggleSubtitleVisibility());
        this.playlistManager.playlistToggleBtn.addEventListener('click', () => this.playlistManager.togglePlaylist());
        this.micToggleBtn.addEventListener('click', () => this.practiceModeManager.togglePracticeMode());
        this.clearRecognitionBtn.addEventListener('click', () => this.practiceModeManager.clearRecognitionText());
        this.recognitionLanguageSelector.addEventListener('change', () => this.practiceModeManager.changeRecognitionLanguage());
        
        this.audioPlayer.addEventListener('play', () => {
            this.audioControlsManager.isPlaying = true;
            this.audioControlsManager.playIcon.style.display = 'none';
            this.audioControlsManager.pauseIcon.style.display = 'block';
        });
        
        this.audioPlayer.addEventListener('pause', () => {
            this.audioControlsManager.isPlaying = false;
            this.audioControlsManager.playIcon.style.display = 'block';
            this.audioControlsManager.pauseIcon.style.display = 'none';
        });
        
        this.audioPlayer.addEventListener('timeupdate', () => {
            this.audioControlsManager.updateProgress();
            this.subtitleManager.updateSubtitle();
            this.repeatLoopManager.checkRepeatLoop();
        });
        
        this.audioPlayer.addEventListener('loadedmetadata', () => {
            this.audioControlsManager.durationEl.textContent = this.audioControlsManager.formatTime(this.audioPlayer.duration);
        });
        
        this.audioPlayer.addEventListener('ended', () => {
            this.audioControlsManager.handleAudioEnded();
        });
        
        this.audioControlsManager.updateVolume();
        this.audioControlsManager.updateSpeed();
        this.practiceModeManager.updateMicButtonState();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new MP3Player();
});
