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
        this.translationSubtitles = [];
        this.currentTranslationIndex = -1;
        
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
        this.subtitleDisplay = document.getElementById('subtitleDisplay');
        this.romajiDisplay = document.getElementById('romajiDisplay');
        this.translationDisplay = document.getElementById('translationDisplay');
        
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

    async loadSubtitles(srtUrl, romajiUrl, translationUrl) {
        if (!srtUrl) {
            this.subtitles = [];
            this.subtitleDisplay.querySelector('.subtitle-text').textContent = '';
            this.romajiSubtitles = [];
            this.romajiDisplay.style.display = 'none';
            this.translationSubtitles = [];
            this.translationDisplay.style.display = 'none';
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
                this.romajiDisplay.style.display = 'block';
                console.log(`Loaded ${this.romajiSubtitles.length} romaji subtitles`);
            } catch (error) {
                console.error('Error loading romaji subtitles:', error);
                this.romajiSubtitles = [];
                this.romajiDisplay.style.display = 'none';
            }
        } else {
            this.romajiSubtitles = [];
            this.romajiDisplay.style.display = 'none';
        }
        
        if (translationUrl) {
            try {
                const response = await fetch(translationUrl);
                const translationText = await response.text();
                this.translationSubtitles = this.parseSRT(translationText);
                this.currentTranslationIndex = -1;
                this.translationDisplay.style.display = 'block';
                console.log(`Loaded ${this.translationSubtitles.length} translation subtitles`);
            } catch (error) {
                console.error('Error loading translation subtitles:', error);
                this.translationSubtitles = [];
                this.translationDisplay.style.display = 'none';
            }
        } else {
            this.translationSubtitles = [];
            this.translationDisplay.style.display = 'none';
        }
    }

    updateSubtitle() {
        const currentTime = this.audioPlayer.currentTime;
        
        if (this.subtitles.length > 0) {
            const subtitleText = this.subtitleDisplay.querySelector('.subtitle-text');
            
            let foundSubtitle = false;
            for (let i = 0; i < this.subtitles.length; i++) {
                const subtitle = this.subtitles[i];
                if (currentTime >= subtitle.start && currentTime <= subtitle.end) {
                    if (this.currentSubtitleIndex !== i) {
                        this.currentSubtitleIndex = i;
                        subtitleText.textContent = subtitle.text;
                        subtitleText.style.opacity = '1';
                    }
                    foundSubtitle = true;
                    break;
                }
            }
            
            if (!foundSubtitle && this.currentSubtitleIndex !== -1) {
                this.currentSubtitleIndex = -1;
                subtitleText.style.opacity = '0';
            }
        }
        
        if (this.romajiSubtitles.length > 0) {
            const romajiText = this.romajiDisplay.querySelector('.romaji-text');
            
            let foundRomaji = false;
            for (let i = 0; i < this.romajiSubtitles.length; i++) {
                const romaji = this.romajiSubtitles[i];
                if (currentTime >= romaji.start && currentTime <= romaji.end) {
                    if (this.currentRomajiIndex !== i) {
                        this.currentRomajiIndex = i;
                        romajiText.textContent = romaji.text;
                        romajiText.style.opacity = '1';
                    }
                    foundRomaji = true;
                    break;
                }
            }
            
            if (!foundRomaji && this.currentRomajiIndex !== -1) {
                this.currentRomajiIndex = -1;
                romajiText.style.opacity = '0';
            }
        }
        
        if (this.translationSubtitles.length > 0) {
            const translationText = this.translationDisplay.querySelector('.translation-text');
            
            let foundTranslation = false;
            for (let i = 0; i < this.translationSubtitles.length; i++) {
                const translation = this.translationSubtitles[i];
                if (currentTime >= translation.start && currentTime <= translation.end) {
                    if (this.currentTranslationIndex !== i) {
                        this.currentTranslationIndex = i;
                        translationText.textContent = translation.text;
                        translationText.style.opacity = '1';
                    }
                    foundTranslation = true;
                    break;
                }
            }
            
            if (!foundTranslation && this.currentTranslationIndex !== -1) {
                this.currentTranslationIndex = -1;
                translationText.style.opacity = '0';
            }
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
        
        await this.loadSubtitles(track.srtUrl, track.srtRomajiUrl, track.srtEnUrl);
        
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

    initEventListeners() {
        this.playPauseBtn.addEventListener('click', () => this.togglePlayPause());
        this.nextBtn.addEventListener('click', () => this.playNext());
        this.prevBtn.addEventListener('click', () => this.playPrevious());
        this.repeatBtn.addEventListener('click', () => this.toggleRepeat());
        this.refreshBtn.addEventListener('click', () => this.requestTracks());
        
        this.progressBar.addEventListener('input', (e) => this.seekTo(e));
        this.volumeSlider.addEventListener('input', () => this.updateVolume());
        this.speedSlider.addEventListener('change', () => this.updateSpeed());
        
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
