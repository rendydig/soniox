import { WebSocketManager } from './websocket-manager.js';

class AudioPlayer {
    constructor() {
        this.recordings = [];
        this.filteredRecordings = [];
        this.currentIndex = -1;
        this.repeatMode = 'off';
        this.isPlaying = false;
        this.currentFilter = 'all';
        
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
        this.speedValue = document.getElementById('speedValue');
        this.playlist = document.getElementById('playlist');
        this.refreshBtn = document.getElementById('refreshBtn');
        this.currentTrackEl = document.getElementById('currentTrack');
        this.trackDetailsEl = document.getElementById('trackDetails');
        
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
            this.requestRecordings();
        } else {
            statusIndicator.className = 'status-indicator disconnected';
            statusText.textContent = 'Disconnected';
        }
    }

    handleWebSocketMessage(data) {
        if (data.type === 'recordings_list') {
            this.recordings = data.recordings;
            this.applyFilter();
        } else if (data.type === 'connection') {
            this.requestRecordings();
        }
    }

    requestRecordings() {
        if (this.wsManager.ws && this.wsManager.ws.readyState === WebSocket.OPEN) {
            this.wsManager.ws.send(JSON.stringify({
                type: 'get_recordings'
            }));
        }
    }

    applyFilter() {
        if (this.currentFilter === 'all') {
            this.filteredRecordings = this.recordings;
        } else if (this.currentFilter === 'host') {
            this.filteredRecordings = this.recordings.filter(r => r.name.toLowerCase().includes('host'));
        } else if (this.currentFilter === 'speaker') {
            this.filteredRecordings = this.recordings.filter(r => r.name.toLowerCase().includes('speaker'));
        }
        this.renderPlaylist();
    }

    renderPlaylist() {
        if (this.filteredRecordings.length === 0) {
            const message = this.recordings.length === 0 ? 'No recordings found' : `No ${this.currentFilter} recordings found`;
            this.playlist.innerHTML = `<div class="empty-state">${message}</div>`;
            return;
        }

        this.playlist.innerHTML = this.filteredRecordings.map((recording, index) => {
            const date = new Date(recording.modified);
            const size = this.formatFileSize(recording.size);
            const isActive = index === this.currentIndex;
            
            return `
                <div class="playlist-item ${isActive ? 'active' : ''}" data-index="${index}">
                    <div class="track-number">${index + 1}</div>
                    <div class="track-details">
                        <div class="track-name">${recording.name}</div>
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

    playTrack(index) {
        if (index < 0 || index >= this.filteredRecordings.length) return;
        
        this.currentIndex = index;
        const recording = this.filteredRecordings[index];
        
        this.audioPlayer.src = recording.url;
        this.audioPlayer.load();
        this.audioPlayer.play();
        
        this.currentTrackEl.textContent = recording.name;
        this.trackDetailsEl.textContent = `Track ${index + 1} of ${this.filteredRecordings.length}`;
        
        this.renderPlaylist();
    }

    togglePlayPause() {
        if (this.currentIndex === -1 && this.filteredRecordings.length > 0) {
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
        if (this.filteredRecordings.length === 0) return;
        
        let nextIndex = this.currentIndex + 1;
        if (nextIndex >= this.filteredRecordings.length) {
            if (this.repeatMode === 'all') {
                nextIndex = 0;
            } else {
                return;
            }
        }
        this.playTrack(nextIndex);
    }

    playPrevious() {
        if (this.filteredRecordings.length === 0) return;
        
        if (this.audioPlayer.currentTime > 3) {
            this.audioPlayer.currentTime = 0;
            return;
        }
        
        let prevIndex = this.currentIndex - 1;
        if (prevIndex < 0) {
            if (this.repeatMode === 'all') {
                prevIndex = this.filteredRecordings.length - 1;
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
        this.speedValue.textContent = `${speed.toFixed(1)}x`;
    }

    initEventListeners() {
        this.playPauseBtn.addEventListener('click', () => this.togglePlayPause());
        this.nextBtn.addEventListener('click', () => this.playNext());
        this.prevBtn.addEventListener('click', () => this.playPrevious());
        this.repeatBtn.addEventListener('click', () => this.toggleRepeat());
        this.refreshBtn.addEventListener('click', () => this.requestRecordings());
        
        this.progressBar.addEventListener('input', (e) => this.seekTo(e));
        this.volumeSlider.addEventListener('input', () => this.updateVolume());
        this.speedSlider.addEventListener('input', () => this.updateSpeed());
        
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
        
        this.audioPlayer.addEventListener('timeupdate', () => this.updateProgress());
        
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
                if (this.currentIndex < this.filteredRecordings.length - 1) {
                    this.playNext();
                }
            }
        });
        
        document.querySelectorAll('.filter-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.currentFilter = btn.dataset.filter;
                document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.applyFilter();
            });
        });
        
        this.updateVolume();
        this.updateSpeed();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new AudioPlayer();
});
