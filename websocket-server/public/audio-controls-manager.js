export class AudioControlsManager {
    constructor(player) {
        this.player = player;
        this.repeatMode = 'off';
        this.isPlaying = false;
        
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
    }

    togglePlayPause() {
        if (this.player.playlistManager.getCurrentIndex() === -1 && this.player.playlistManager.getTracks().length > 0) {
            this.player.playTrack(0);
            return;
        }
        
        if (this.audioPlayer.paused) {
            this.audioPlayer.play();
        } else {
            this.audioPlayer.pause();
        }
    }

    playNext() {
        const tracks = this.player.playlistManager.getTracks();
        if (tracks.length === 0) return;
        
        let nextIndex = this.player.playlistManager.getCurrentIndex() + 1;
        if (nextIndex >= tracks.length) {
            if (this.repeatMode === 'all') {
                nextIndex = 0;
            } else {
                return;
            }
        }
        this.player.playTrack(nextIndex);
    }

    playPrevious() {
        const tracks = this.player.playlistManager.getTracks();
        if (tracks.length === 0) return;
        
        if (this.audioPlayer.currentTime > 3) {
            this.audioPlayer.currentTime = 0;
            return;
        }
        
        let prevIndex = this.player.playlistManager.getCurrentIndex() - 1;
        if (prevIndex < 0) {
            if (this.repeatMode === 'all') {
                prevIndex = tracks.length - 1;
            } else {
                return;
            }
        }
        this.player.playTrack(prevIndex);
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

    handleAudioEnded() {
        if (this.repeatMode === 'one') {
            this.audioPlayer.currentTime = 0;
            this.audioPlayer.play();
        } else if (this.repeatMode === 'all') {
            this.playNext();
        } else {
            const tracks = this.player.playlistManager.getTracks();
            const currentIndex = this.player.playlistManager.getCurrentIndex();
            if (currentIndex < tracks.length - 1) {
                this.playNext();
            }
        }
    }
}
