import { GameProgressTracker } from './game-progress-tracker.js';

export class GameSelector {
    constructor() {
        this.modal = document.getElementById('gameSelectorModal');
        this.modalBody = null;
        this.gameList = document.getElementById('gameList');
        this.closeBtn = document.getElementById('closeModalBtn');
        this.gameSelectorBtn = document.getElementById('gameSelectorBtn');
        this.searchInput = document.getElementById('gameSearchInput');
        this.games = [];
        this.filteredGames = [];
        this.currentFile = null;
        this.progressTracker = new GameProgressTracker();
        
        this.itemsPerPage = 6;
        this.currentPage = 0;
        this.isLoading = false;
        this.hasMore = true;
        this.searchQuery = '';
        
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

        this.searchInput.addEventListener('input', (e) => {
            this.handleSearch(e.target.value);
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
            this.filteredGames = [...this.games];
            this.resetPagination();
            this.renderInitialGames();
        } catch (error) {
            console.error('Error loading games:', error);
            this.gameList.innerHTML = `
                <div class="loading-spinner" style="color: var(--danger);">
                    Failed to load games. Please try again.
                </div>
            `;
        }
    }

    resetPagination() {
        this.currentPage = 0;
        this.hasMore = true;
        this.isLoading = false;
    }

    renderInitialGames() {
        if (this.filteredGames.length === 0) {
            this.gameList.innerHTML = `
                <div class="loading-spinner">
                    No games found.
                </div>
            `;
            return;
        }

        this.gameList.innerHTML = '';
        this.loadMoreGames();
    }

    loadMoreGames() {
        if (this.isLoading || !this.hasMore) return;

        this.isLoading = true;
        const startIndex = this.currentPage * this.itemsPerPage;
        const endIndex = startIndex + this.itemsPerPage;
        const gamesToRender = this.filteredGames.slice(startIndex, endIndex);

        if (gamesToRender.length === 0) {
            this.hasMore = false;
            this.isLoading = false;
            return;
        }

        gamesToRender.forEach((game, index) => {
            setTimeout(() => {
                this.renderGameCard(game);
            }, index * 50);
        });

        this.currentPage++;
        this.hasMore = endIndex < this.filteredGames.length;
        this.isLoading = false;
    }

    renderGameCard(game) {
        const gameCard = document.createElement('div');
        gameCard.className = 'game-card game-card-fade-in';
        
        if (this.currentFile === game.file) {
            gameCard.classList.add('active');
        }

        const gameStatus = this.progressTracker.getGameStatus(game.file);
        const statusBadge = this.getStatusBadge(gameStatus);
        const imageUrl = this.getGameImageUrl(game.image);

        gameCard.innerHTML = `
            <div class="game-card-image">
                <img src="${imageUrl}" alt="${game.title}" />
            </div>
            <div class="game-card-content">
                <div class="game-card-header">
                    <div style="flex: 1;">
                        <h3 class="game-card-title">${game.title}</h3>
                        ${statusBadge}
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
            </div>
        `;

        gameCard.addEventListener('click', () => {
            this.selectGame(game.file);
        });

        this.gameList.appendChild(gameCard);
    }

    handleScroll() {
        if (!this.modalBody) return;
        
        const scrollTop = this.modalBody.scrollTop;
        const scrollHeight = this.modalBody.scrollHeight;
        const clientHeight = this.modalBody.clientHeight;

        if (scrollTop + clientHeight >= scrollHeight - 100) {
            this.loadMoreGames();
        }
    }

    handleSearch(query) {
        this.searchQuery = query.trim().toLowerCase();
        
        if (this.searchQuery === '') {
            this.filteredGames = [...this.games];
        } else {
            const keywords = this.searchQuery.split(/\s+/).filter(k => k.length > 0);
            
            this.filteredGames = this.games.filter(game => {
                const title = game.title.toLowerCase();
                return keywords.some(keyword => title.includes(keyword));
            });
        }

        this.resetPagination();
        this.renderInitialGames();
    }

    getStatusBadge(gameStatus) {
        if (!gameStatus) {
            return '';
        }

        if (gameStatus.status === 'finished') {
            return '<span class="game-status-badge status-finished">✓ Finished</span>';
        } else if (gameStatus.status === 'in-progress') {
            return '<span class="game-status-badge status-in-progress">● In Progress</span>';
        }

        return '';
    }

    getGameImageUrl(imageName) {
        if (!imageName || imageName.trim() === '') {
            return '/assets/images/default.jpeg';
        }
        return `/assets/images/${imageName}`;
    }

    selectGame(filename) {
        // const fileWithoutExt = filename.replace('.json', '');
        window.location.href = `roleplay-player.html?file=${filename}`;
    }

    openModal() {
        this.currentFile = this.getCurrentFile();
        this.modal.classList.add('active');
        this.searchInput.value = '';
        this.searchQuery = '';
        
        if (!this.modalBody) {
            this.modalBody = this.modal.querySelector('.modal-body');
            if (this.modalBody) {
                this.modalBody.addEventListener('scroll', () => {
                    this.handleScroll();
                });
            }
        }
        
        if (this.games.length === 0) {
            this.loadGames();
        } else {
            this.filteredGames = [...this.games];
            this.resetPagination();
            this.renderInitialGames();
        }
    }

    closeModal() {
        this.modal.classList.remove('active');
    }

    getCurrentFile() {
        const params = new URLSearchParams(window.location.search);
        const file = params.get('file');
        return file || 'english-1.json';
    }
}
