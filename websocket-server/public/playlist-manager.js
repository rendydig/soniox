export class PlaylistManager {
    constructor(player) {
        this.player = player;
        this.tracks = [];
        this.currentIndex = -1;
        
        this.playlist = document.getElementById('playlist');
        this.playlistSidebar = document.getElementById('playlistSidebar');
        this.playlistToggleBtn = document.getElementById('playlistToggleBtn');
    }

    setTracks(tracks) {
        this.tracks = tracks;
        this.renderPlaylist();
    }

    getTracks() {
        return this.tracks;
    }

    getCurrentIndex() {
        return this.currentIndex;
    }

    setCurrentIndex(index) {
        this.currentIndex = index;
    }

    getCurrentTrack() {
        if (this.currentIndex >= 0 && this.currentIndex < this.tracks.length) {
            return this.tracks[this.currentIndex];
        }
        return null;
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
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="12" y1="5" x2="12" y2="19"/>
                            <line x1="5" y1="12" x2="19" y2="12"/>
                        </svg>
                    </button>
                </div>
            `;
        }).join('');

        document.querySelectorAll('.play-track-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const index = parseInt(btn.dataset.index);
                this.player.loadTrack(index);
            });
        });

        document.querySelectorAll('.playlist-item').forEach(item => {
            item.addEventListener('click', () => {
                const index = parseInt(item.dataset.index);
                this.player.loadTrack(index);
            });
        });
    }

    formatFileSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    togglePlaylist() {
        this.playlistSidebar.classList.toggle('closed');
        document.body.classList.toggle('playlist-closed');
    }

    requestTracks(wsManager) {
        if (wsManager.ws && wsManager.ws.readyState === WebSocket.OPEN) {
            wsManager.ws.send(JSON.stringify({
                type: 'get_mp3_tracks'
            }));
        }
    }
}
