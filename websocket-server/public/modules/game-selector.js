export class GameSelector {
    constructor() {
        this.modal = document.getElementById('gameSelectorModal');
        this.gameList = document.getElementById('gameList');
        this.closeBtn = document.getElementById('closeModalBtn');
        this.gameSelectorBtn = document.getElementById('gameSelectorBtn');
        this.games = [];
        this.currentFile = null;
        
        this.bindEvents();
    }

    bindEvents() {
        this.gameSelectorBtn.addEventListener('click', () => {
            this.openModal();
        });

        this.closeBtn.addEventListener('click', () => {
            this.closeModal();
        });

        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) {
                this.closeModal();
            }
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.modal.classList.contains('active')) {
                this.closeModal();
            }
        });
    }

    async loadGames() {
        try {
            const response = await fetch('/assets/maps-english.json');
            if (!response.ok) {
                throw new Error('Failed to load game maps');
            }
            const data = await response.json();
            this.games = data.games;
            this.renderGames();
        } catch (error) {
            console.error('Error loading games:', error);
            this.gameList.innerHTML = `
                <div class="loading-spinner" style="color: var(--danger);">
                    Failed to load games. Please try again.
                </div>
            `;
        }
    }

    renderGames() {
        if (this.games.length === 0) {
            this.gameList.innerHTML = `
                <div class="loading-spinner">
                    No games available.
                </div>
            `;
            return;
        }

        this.gameList.innerHTML = '';
        
        this.games.forEach((game) => {
            const gameCard = document.createElement('div');
            gameCard.className = 'game-card';
            
            if (this.currentFile === game.file) {
                gameCard.classList.add('active');
            }

            gameCard.innerHTML = `
                <div class="game-card-header">
                    <div style="flex: 1;">
                        <h3 class="game-card-title">${game.title}</h3>
                    </div>
                    <div class="game-card-duration">
                        ${game.estimated_duration_minutes} min
                    </div>
                </div>
                <p class="game-card-theme">${game.theme}</p>
                <div class="game-card-participants">
                    ${game.participants.map(p => 
                        `<span class="participant-badge">${p}</span>`
                    ).join('')}
                </div>
            `;

            gameCard.addEventListener('click', () => {
                this.selectGame(game.file);
            });

            this.gameList.appendChild(gameCard);
        });
    }

    selectGame(filename) {
        // const fileWithoutExt = filename.replace('.json', '');
        window.location.href = `roleplay-player.html?file=${filename}`;
    }

    openModal() {
        this.currentFile = this.getCurrentFile();
        this.modal.classList.add('active');
        if (this.games.length === 0) {
            this.loadGames();
        } else {
            this.renderGames();
        }
    }

    closeModal() {
        this.modal.classList.remove('active');
    }

    getCurrentFile() {
        const params = new URLSearchParams(window.location.search);
        const file = params.get('file');
        return file ? `${file}.json` : 'english-1.json';
    }
}
