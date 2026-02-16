import { WebSocketManager } from './websocket-manager.js';

class MP3Player {
    constructor() {
        this.tracks = [];
        this.currentIndex = -1;
        this.repeatMode = 'off';
        this.isPlaying = false;
        this.subtitles = [];
        this.currentSubtitleIndex = -1;
        this.romajiSubtitles = [];
        this.currentRomajiIndex = -1;
        this.translationEnSubtitles = [];
        this.translationIdSubtitles = [];
        this.currentTranslationIndex = -1;
        this.currentTranslationLang = 'en';
        
        this.audioPlayer = document.getElementById('audioPlayer');
        this.playPauseBtn = document.getElementById('playPauseBtn');
        this.playIcon = document.getElementById('playIcon');
        this.pauseIcon = document.getElementById('pauseIcon');
        this.prevBtn = document.getElementById('prevBtn');
        this.nextBtn = document.getElementById('nextBtn');
        this.repeatBtn = document.getElementById('repeatBtn');
        this.repeatOffIcon = document.getElementById('repeatOffIcon');
        this.repeatAllIcon = document.getElementById('repeatAllIcon');
        this.repeatOneIcon = document.getElementById('repeatOneIcon');
        this.progressBar = document.getElementById('progressBar');
        this.currentTimeEl = document.getElementById('currentTime');
        this.durationEl = document.getElementById('duration');
        this.volumeSlider = document.getElementById('volumeSlider');
        this.speedSlider = document.getElementById('speedSlider');
        this.playlist = document.getElementById('playlist');
        this.refreshBtn = document.getElementById('refreshBtn');
        this.currentTrackEl = document.getElementById('currentTrack');
        this.trackDetailsEl = document.getElementById('trackDetails');
        this.subtitleList = document.getElementById('subtitleList');
        this.translationLanguageSelector = document.getElementById('translationLanguage');
        this.showSubtitleCheckbox = document.getElementById('showSubtitle');
        this.showRomajiCheckbox = document.getElementById('showRomaji');
        this.showTranslationCheckbox = document.getElementById('showTranslation');
        this.currentActiveIndex = -1;
        this.playlistToggleBtn = document.getElementById('playlistToggleBtn');
        this.playlistSidebar = document.getElementById('playlistSidebar');
        this.repeatLoopActive = false;
        this.repeatLoopStart = 0;
        this.repeatLoopEnd = 0;
        this.repeatLoopDelaying = false;
        this.repeatLoopDelayTimeout = null;
        
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
            this.requestTracks();
        } else {
            statusIndicator.className = 'status-indicator disconnected';
            statusText.textContent = 'Disconnected';
        }
    }

    handleWebSocketMessage(data) {
        if (data.type === 'mp3_list') {
            this.tracks = data.tracks;
            this.renderPlaylist();
        } else if (data.type === 'connection') {
            this.requestTracks();
        }
    }

    requestTracks() {
        if (this.wsManager.ws && this.wsManager.ws.readyState === WebSocket.OPEN) {
            this.wsManager.ws.send(JSON.stringify({
                type: 'get_mp3_tracks'
            }));
        }
    }

    renderPlaylist() {
        if (this.tracks.length === 0) {
            this.playlist.innerHTML = '<div class="empty-state">No tracks found</div>';
            return;
        }

        this.playlist.innerHTML = this.tracks.map((track, index) => {
            const date = new Date(track.modified);
            const size = this.formatFileSize(track.size);
            const isActive = index === this.currentIndex;
            
            return `
                <div class="playlist-item ${isActive ? 'active' : ''}" data-index="${index}">
                    <div class="track-number">${index + 1}</div>
                    <div class="track-details">
                        <div class="track-name">${track.name}</div>
                        <div class="track-meta">${size} • ${date.toLocaleDateString()} ${date.toLocaleTimeString()}</div>
                    </div>
                    <button class="play-track-btn" data-index="${index}">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M8 5v14l11-7z"/>
                        </svg>
                    </button>
                </div>
            `;
        }).join('');

        document.querySelectorAll('.play-track-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const index = parseInt(btn.dataset.index);
                this.playTrack(index);
            });
        });

        document.querySelectorAll('.playlist-item').forEach(item => {
            item.addEventListener('click', () => {
                const index = parseInt(item.dataset.index);
                this.playTrack(index);
            });
        });
    }

    formatFileSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    parseSRT(srtText) {
        const subtitles = [];
        const blocks = srtText.trim().split(/\n\s*\n/);
        
        for (const block of blocks) {
            const lines = block.split('\n');
            if (lines.length < 3) continue;
            
            const timeLine = lines[1];
            const timeMatch = timeLine.match(/(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-+>\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})/);
            
            if (timeMatch) {
                const startTime = parseInt(timeMatch[1]) * 3600 + parseInt(timeMatch[2]) * 60 + parseInt(timeMatch[3]) + parseInt(timeMatch[4]) / 1000;
                const endTime = parseInt(timeMatch[5]) * 3600 + parseInt(timeMatch[6]) * 60 + parseInt(timeMatch[7]) + parseInt(timeMatch[8]) / 1000;
                const text = lines.slice(2).join('\n');
                
                subtitles.push({
                    start: startTime,
                    end: endTime,
                    text: text
                });
            }
        }
        
        return subtitles;
    }

    async loadSubtitles(srtUrl, romajiUrl, translationEnUrl, translationIdUrl) {
        if (!srtUrl) {
            this.subtitles = [];
            this.romajiSubtitles = [];
            this.translationEnSubtitles = [];
            this.translationIdSubtitles = [];
            this.renderSubtitleList();
            return;
        }
        
        try {
            const response = await fetch(srtUrl);
            const srtText = await response.text();
            this.subtitles = this.parseSRT(srtText);
            this.currentSubtitleIndex = -1;
            console.log(`Loaded ${this.subtitles.length} subtitles`);
        } catch (error) {
            console.error('Error loading subtitles:', error);
            this.subtitles = [];
        }
        
        if (romajiUrl) {
            try {
                const response = await fetch(romajiUrl);
                const romajiText = await response.text();
                this.romajiSubtitles = this.parseSRT(romajiText);
                this.currentRomajiIndex = -1;
                console.log(`Loaded ${this.romajiSubtitles.length} romaji subtitles`);
            } catch (error) {
                console.error('Error loading romaji subtitles:', error);
                this.romajiSubtitles = [];
            }
        } else {
            this.romajiSubtitles = [];
        }
        
        let hasEnTranslation = false;
        let hasIdTranslation = false;
        
        if (translationEnUrl) {
            try {
                const response = await fetch(translationEnUrl);
                const translationText = await response.text();
                this.translationEnSubtitles = this.parseSRT(translationText);
                hasEnTranslation = true;
                console.log(`Loaded ${this.translationEnSubtitles.length} English translation subtitles`);
            } catch (error) {
                console.error('Error loading English translation subtitles:', error);
                this.translationEnSubtitles = [];
            }
        } else {
            this.translationEnSubtitles = [];
        }
        
        if (translationIdUrl) {
            try {
                const response = await fetch(translationIdUrl);
                const translationText = await response.text();
                this.translationIdSubtitles = this.parseSRT(translationText);
                hasIdTranslation = true;
                console.log(`Loaded ${this.translationIdSubtitles.length} Indonesian translation subtitles`);
            } catch (error) {
                console.error('Error loading Indonesian translation subtitles:', error);
                this.translationIdSubtitles = [];
            }
        } else {
            this.translationIdSubtitles = [];
        }
        
        if (hasEnTranslation || hasIdTranslation) {
            this.currentTranslationIndex = -1;
            
            if (hasEnTranslation && hasIdTranslation) {
                this.translationLanguageSelector.style.display = 'block';
                this.currentTranslationLang = 'en';
                this.translationLanguageSelector.value = 'en';
            } else if (hasEnTranslation) {
                this.translationLanguageSelector.style.display = 'none';
                this.currentTranslationLang = 'en';
            } else if (hasIdTranslation) {
                this.translationLanguageSelector.style.display = 'none';
                this.currentTranslationLang = 'id';
            }
        } else {
            this.translationLanguageSelector.style.display = 'none';
        }
        
        this.renderSubtitleList();
    }

    renderSubtitleList() {
        if (this.subtitles.length === 0) {
            this.subtitleList.innerHTML = '<div class="empty-subtitle-state">No subtitles available</div>';
            return;
        }
        
        const showSubtitle = this.showSubtitleCheckbox.checked;
        const showRomaji = this.showRomajiCheckbox.checked && this.romajiSubtitles.length > 0;
        const showTranslation = this.showTranslationCheckbox.checked && 
            (this.translationEnSubtitles.length > 0 || this.translationIdSubtitles.length > 0);
        
        const activeTranslationSubtitles = this.currentTranslationLang === 'en' 
            ? this.translationEnSubtitles 
            : this.translationIdSubtitles;
        
        this.subtitleList.innerHTML = this.subtitles.map((subtitle, index) => {
            const romaji = this.romajiSubtitles[index] || null;
            const translation = activeTranslationSubtitles[index] || null;
            
            let content = '';
            
            if (showSubtitle) {
                content += `<div class="subtitle-line-text">${subtitle.text}</div>`;
            }
            
            if (showRomaji && romaji) {
                content += `<div class="subtitle-line-romaji">${romaji.text}</div>`;
            }
            
            if (showTranslation && translation) {
                content += `<div class="subtitle-line-translation">${translation.text}</div>`;
            }
            
            return `
                <div class="subtitle-line-item" data-index="${index}" data-start="${subtitle.start}" data-end="${subtitle.end}">
                    <div class="subtitle-content">
                        ${content}
                    </div>
                    <button class="subtitle-repeat-btn" data-index="${index}" data-start="${subtitle.start}" data-end="${subtitle.end}" title="Repeat this subtitle">
                        <span class="material-icons">repeat</span>
                    </button>
                </div>
            `;
        }).join('');
        
        document.querySelectorAll('.subtitle-line-item').forEach(item => {
            item.addEventListener('click', (e) => {
                if (!e.target.closest('.subtitle-repeat-btn')) {
                    const start = parseFloat(item.dataset.start);
                    this.audioPlayer.currentTime = start;
                }
            });
        });
        
        document.querySelectorAll('.subtitle-repeat-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const start = parseFloat(btn.dataset.start);
                const end = parseFloat(btn.dataset.end);
                this.toggleSubtitleRepeat(start, end, btn);
            });
        });
    }
    
    updateSubtitle() {
        const currentTime = this.audioPlayer.currentTime;
        
        if (this.subtitles.length === 0) return;
        
        if (this.repeatLoopActive) {
            return;
        }
        
        let foundIndex = -1;
        for (let i = 0; i < this.subtitles.length; i++) {
            const subtitle = this.subtitles[i];
            if (currentTime >= subtitle.start && currentTime <= subtitle.end) {
                foundIndex = i;
                break;
            }
        }
        
        if (foundIndex !== this.currentActiveIndex) {
            const previousActive = this.subtitleList.querySelector('.subtitle-line-item.active');
            if (previousActive) {
                previousActive.classList.remove('active');
            }
            
            if (foundIndex !== -1) {
                const activeItem = this.subtitleList.querySelector(`.subtitle-line-item[data-index="${foundIndex}"]`);
                if (activeItem) {
                    activeItem.classList.add('active');
                    activeItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }
            
            this.currentActiveIndex = foundIndex;
        }
    }

    async playTrack(index) {
        if (index < 0 || index >= this.tracks.length) return;
        
        this.currentIndex = index;
        const track = this.tracks[index];
        
        this.audioPlayer.src = track.url;
        this.audioPlayer.load();
        this.audioPlayer.play();
        
        this.currentTrackEl.textContent = track.name;
        this.trackDetailsEl.textContent = `Track ${index + 1} of ${this.tracks.length}`;
        
        await this.loadSubtitles(track.srtUrl, track.srtRomajiUrl, track.srtEnUrl, track.srtIdUrl);
        
        this.renderPlaylist();
    }

    togglePlayPause() {
        if (this.currentIndex === -1 && this.tracks.length > 0) {
            this.playTrack(0);
            return;
        }
        
        if (this.audioPlayer.paused) {
            this.audioPlayer.play();
        } else {
            this.audioPlayer.pause();
        }
    }

    playNext() {
        if (this.tracks.length === 0) return;
        
        let nextIndex = this.currentIndex + 1;
        if (nextIndex >= this.tracks.length) {
            if (this.repeatMode === 'all') {
                nextIndex = 0;
            } else {
                return;
            }
        }
        this.playTrack(nextIndex);
    }

    playPrevious() {
        if (this.tracks.length === 0) return;
        
        if (this.audioPlayer.currentTime > 3) {
            this.audioPlayer.currentTime = 0;
            return;
        }
        
        let prevIndex = this.currentIndex - 1;
        if (prevIndex < 0) {
            if (this.repeatMode === 'all') {
                prevIndex = this.tracks.length - 1;
            } else {
                return;
            }
        }
        this.playTrack(prevIndex);
    }

    toggleRepeat() {
        const modes = ['off', 'all', 'one'];
        const currentModeIndex = modes.indexOf(this.repeatMode);
        this.repeatMode = modes[(currentModeIndex + 1) % modes.length];
        
        this.repeatBtn.classList.remove('repeat-off', 'repeat-all', 'repeat-one');
        this.repeatBtn.classList.add(`repeat-${this.repeatMode}`);
        
        this.repeatOffIcon.style.display = 'none';
        this.repeatAllIcon.style.display = 'none';
        this.repeatOneIcon.style.display = 'none';
        
        const titles = {
            'off': 'Repeat Off',
            'all': 'Repeat All',
            'one': 'Repeat One'
        };
        this.repeatBtn.title = titles[this.repeatMode];
        
        if (this.repeatMode === 'off') {
            this.repeatOffIcon.style.display = 'block';
            this.audioPlayer.loop = false;
        } else if (this.repeatMode === 'all') {
            this.repeatAllIcon.style.display = 'block';
            this.audioPlayer.loop = false;
        } else if (this.repeatMode === 'one') {
            this.repeatOneIcon.style.display = 'block';
            this.audioPlayer.loop = true;
        }
    }

    updateProgress() {
        if (this.audioPlayer.duration) {
            const progress = (this.audioPlayer.currentTime / this.audioPlayer.duration) * 100;
            this.progressBar.value = progress;
            
            this.currentTimeEl.textContent = this.formatTime(this.audioPlayer.currentTime);
            this.durationEl.textContent = this.formatTime(this.audioPlayer.duration);
        }
    }

    formatTime(seconds) {
        if (isNaN(seconds)) return '0:00';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }

    seekTo(event) {
        if (this.audioPlayer.duration) {
            const seekTime = (event.target.value / 100) * this.audioPlayer.duration;
            this.audioPlayer.currentTime = seekTime;
        }
    }

    updateVolume() {
        this.audioPlayer.volume = this.volumeSlider.value / 100;
    }

    updateSpeed() {
        const speed = parseFloat(this.speedSlider.value);
        this.audioPlayer.playbackRate = speed;
    }

    switchTranslationLanguage() {
        this.currentTranslationLang = this.translationLanguageSelector.value;
        this.currentTranslationIndex = -1;
        this.renderSubtitleList();
    }
    
    toggleSubtitleVisibility() {
        this.renderSubtitleList();
    }

    togglePlaylist() {
        this.playlistSidebar.classList.toggle('closed');
        document.body.classList.toggle('playlist-closed');
    }

    toggleSubtitleRepeat(start, end, buttonElement) {
        if (this.repeatLoopActive && this.repeatLoopStart === start && this.repeatLoopEnd === end) {
            this.repeatLoopActive = false;
            this.repeatLoopStart = 0;
            this.repeatLoopEnd = 0;
            this.repeatLoopDelaying = false;
            if (this.repeatLoopDelayTimeout) {
                clearTimeout(this.repeatLoopDelayTimeout);
                this.repeatLoopDelayTimeout = null;
            }
            document.querySelectorAll('.subtitle-repeat-btn').forEach(btn => {
                btn.classList.remove('active');
            });
        } else {
            if (this.repeatLoopDelayTimeout) {
                clearTimeout(this.repeatLoopDelayTimeout);
                this.repeatLoopDelayTimeout = null;
            }
            this.repeatLoopActive = true;
            this.repeatLoopStart = start;
            this.repeatLoopEnd = end;
            this.repeatLoopDelaying = false;
            this.audioPlayer.currentTime = start;
            document.querySelectorAll('.subtitle-repeat-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            buttonElement.classList.add('active');
        }
    }

    checkRepeatLoop() {
        if (this.repeatLoopActive && !this.repeatLoopDelaying && this.audioPlayer.currentTime >= this.repeatLoopEnd) {
            this.repeatLoopDelaying = true;
            this.audioPlayer.pause();
            
            this.repeatLoopDelayTimeout = setTimeout(() => {
                this.audioPlayer.currentTime = this.repeatLoopStart;
                this.audioPlayer.play();
                this.repeatLoopDelaying = false;
            }, 2000);
        }
    }

    initEventListeners() {
        this.playPauseBtn.addEventListener('click', () => this.togglePlayPause());
        this.nextBtn.addEventListener('click', () => this.playNext());
        this.prevBtn.addEventListener('click', () => this.playPrevious());
        this.repeatBtn.addEventListener('click', () => this.toggleRepeat());
        this.refreshBtn.addEventListener('click', () => this.requestTracks());
        
        this.progressBar.addEventListener('input', (e) => this.seekTo(e));
        this.volumeSlider.addEventListener('input', () => this.updateVolume());
        this.speedSlider.addEventListener('change', () => this.updateSpeed());
        this.translationLanguageSelector.addEventListener('change', () => this.switchTranslationLanguage());
        this.showSubtitleCheckbox.addEventListener('change', () => this.toggleSubtitleVisibility());
        this.showRomajiCheckbox.addEventListener('change', () => this.toggleSubtitleVisibility());
        this.showTranslationCheckbox.addEventListener('change', () => this.toggleSubtitleVisibility());
        this.playlistToggleBtn.addEventListener('click', () => this.togglePlaylist());
        
        this.audioPlayer.addEventListener('play', () => {
            this.isPlaying = true;
            this.playIcon.style.display = 'none';
            this.pauseIcon.style.display = 'block';
        });
        
        this.audioPlayer.addEventListener('pause', () => {
            this.isPlaying = false;
            this.playIcon.style.display = 'block';
            this.pauseIcon.style.display = 'none';
        });
        
        this.audioPlayer.addEventListener('timeupdate', () => {
            this.updateProgress();
            this.updateSubtitle();
            this.checkRepeatLoop();
        });
        
        this.audioPlayer.addEventListener('loadedmetadata', () => {
            this.durationEl.textContent = this.formatTime(this.audioPlayer.duration);
        });
        
        this.audioPlayer.addEventListener('ended', () => {
            if (this.repeatMode === 'one') {
                this.audioPlayer.currentTime = 0;
                this.audioPlayer.play();
            } else if (this.repeatMode === 'all') {
                this.playNext();
            } else {
                if (this.currentIndex < this.tracks.length - 1) {
                    this.playNext();
                }
            }
        });
        
        this.updateVolume();
        this.updateSpeed();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new MP3Player();
});
