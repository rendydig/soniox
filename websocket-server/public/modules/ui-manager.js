import { MOBILE_BREAKPOINT } from './constants.js';

export class UIManager {
    constructor() {
        this.sidebarCollapsed = false;
        this.elements = this.initElements();
        this.initSidebar();
    }

    initElements() {
        return {
            title: document.getElementById('conversationTitle'),
            meta: document.getElementById('conversationMeta'),
            turnCounter: document.getElementById('turnCounter'),
            stateLabel: document.getElementById('stateLabel'),
            progressFill: document.getElementById('progressFill'),
            conversationHistory: document.getElementById('conversationHistory'),
            turnPrompt: document.getElementById('turnPrompt'),
            turnHint: document.getElementById('turnHint'),
            retryBtn: document.getElementById('retryBtn'),
            micStatusDot: document.getElementById('micStatusDot'),
            micStatusText: document.getElementById('micStatusText'),
            attemptInfo: document.getElementById('attemptInfo'),
            transcriptOutput: document.getElementById('transcriptOutput'),
            resultOutput: document.getElementById('resultOutput'),
            manualInput: document.getElementById('manualInput'),
            submitManualBtn: document.getElementById('submitManualBtn'),
            expectedWrap: document.getElementById('expectedWrap'),
            expectedOutput: document.getElementById('expectedOutput'),
            scoreLabel: document.querySelector('#scoreLabel'),
            currentSpeakerStat: document.getElementById('currentSpeakerStat'),
            completedTurnsStat: document.getElementById('completedTurnsStat'),
            streakStat: document.getElementById('streakStat'),
            fileNameStat: document.getElementById('fileNameStat'),
            restartBtn: document.getElementById('restartBtn'),
            sidebarPanel: document.getElementById('sidebarPanel'),
            sidebarToggle: document.getElementById('sidebarToggle'),
            toggleScore: document.getElementById('toggleScore')
        };
    }

    initSidebar() {
        const savedState = localStorage.getItem('roleplay-sidebar-collapsed');
        this.sidebarCollapsed = savedState !== null ? savedState === 'true' : true;
        this.updateSidebarState();
    }

    toggleSidebar() {
        this.sidebarCollapsed = !this.sidebarCollapsed;
        this.updateSidebarState();
        localStorage.setItem('roleplay-sidebar-collapsed', String(this.sidebarCollapsed));
    }

    updateSidebarState() {
        if (this.sidebarCollapsed) {
            this.elements.sidebarPanel.classList.add('collapsed');
            document.body.classList.add('sidebar-collapsed');
        } else {
            this.elements.sidebarPanel.classList.remove('collapsed');
            document.body.classList.remove('sidebar-collapsed');
        }
    }

    setState(nextState) {
        this.elements.stateLabel.textContent = nextState;
    }

    updateMicStatus(text, tone) {
        this.elements.micStatusText.textContent = text;
        this.elements.micStatusDot.classList.remove('listening', 'processing');
        if (tone === 'listening' || tone === 'processing') {
            this.elements.micStatusDot.classList.add(tone);
        }
    }

    updateTranscript(text, hasValue, forceEmptyStyle = false) {
        this.elements.transcriptOutput.textContent = text;
        this.elements.transcriptOutput.classList.toggle('empty', forceEmptyStyle || !hasValue);
    }

    updateResult(text, success, forceEmptyStyle = false) {
        this.elements.resultOutput.textContent = text;
        this.elements.resultOutput.classList.toggle('empty', forceEmptyStyle);
        this.elements.resultOutput.style.borderColor = success ? 'rgba(34, 197, 94, 0.35)' : 'rgba(148, 163, 184, 0.16)';
    }

    updateStats(turn, score, completedTurns, streak) {
        this.elements.scoreLabel.textContent = `Score: ${score}`;
        this.elements.toggleScore.textContent = String(score);
        this.elements.currentSpeakerStat.textContent = turn?.speaker || '-';
        this.elements.completedTurnsStat.textContent = String(completedTurns);
        this.elements.streakStat.textContent = String(streak);
    }

    updateProgress(currentIndex, totalTurns) {
        this.elements.turnCounter.textContent = `${currentIndex + 1} / ${totalTurns}`;
        this.elements.progressFill.style.height = `${((currentIndex) / totalTurns) * 100}%`;
    }

    renderConversationMeta(conversation) {
        this.elements.title.textContent = conversation.title || 'Roleplay conversation';
        const duration = conversation.estimated_duration_minutes
            ? `${conversation.estimated_duration_minutes} min`
            : 'Unknown duration';
        const theme = conversation.theme || 'Conversation practice';
        const dialogueLength = Array.isArray(conversation.dialogue) ? conversation.dialogue.length : 0;
        this.elements.meta.textContent = `${theme} • ${duration} • ${dialogueLength} turns`;
    }

    renderConversationHistory(dialogue, currentTurnIndex, onReplayClick) {
        this.elements.conversationHistory.innerHTML = '';

        for (let i = 0; i <= currentTurnIndex; i++) {
            const turn = dialogue[i];
            if (!turn) continue;

            const isCurrent = i === currentTurnIndex;
            const turnCard = this.createTurnCard(turn, i, isCurrent, onReplayClick);
            this.elements.conversationHistory.appendChild(turnCard);
        }

        this.scrollToBottom();
    }

    createTurnCard(turn, turnIndex, isCurrent, onReplayClick) {
        const card = document.createElement('article');
        card.className = `turn-card ${isCurrent ? 'current-turn' : 'history-turn'}`;
        card.dataset.turnIndex = turnIndex;

        const header = document.createElement('div');
        header.className = 'turn-card-header';

        const speakerBadge = document.createElement('span');
        speakerBadge.className = 'speaker-badge';
        speakerBadge.textContent = turn.speaker == "You" ? "Your turn " : turn.speaker;

        const turnTime = document.createElement('span');
        turnTime.className = 'turn-time';
        turnTime.textContent = turn.time || '--:--';

        header.appendChild(speakerBadge);
        header.appendChild(turnTime);

        const content = document.createElement('div');
        content.className = 'turn-card-content';

        const englishLine = document.createElement('h2');
        englishLine.className = 'turn-card-english';
        englishLine.textContent = turn.english || '';

        const translationLine = document.createElement('p');
        translationLine.className = 'turn-card-translation';
        translationLine.textContent = turn.indonesian || '';

        const replayBtn = document.createElement('button');
        replayBtn.className = 'turn-card-replay';
        replayBtn.innerHTML = '<span class="material-icons">volume_up</span> Replay';
        replayBtn.addEventListener('click', () => onReplayClick(turnIndex));

        content.appendChild(englishLine);
        content.appendChild(translationLine);
        content.appendChild(replayBtn);

        card.appendChild(header);
        card.appendChild(content);

        return card;
    }

    renderCompletedHistory(dialogue, onReplayClick) {
        this.elements.conversationHistory.innerHTML = '';
        for (let i = 0; i < dialogue.length; i++) {
            const turn = dialogue[i];
            if (!turn) continue;
            const turnCard = this.createTurnCard(turn, i, false, onReplayClick);
            this.elements.conversationHistory.appendChild(turnCard);
        }
    }

    scrollToBottom() {
        const container = this.elements.conversationHistory;
        setTimeout(() => {
            container.scrollTop = container.scrollHeight;
        }, 100);
    }

    showExpectedLine(text) {
        this.elements.expectedWrap.classList.remove('hidden');
        this.elements.expectedOutput.textContent = text;
    }

    hideExpectedLine() {
        this.elements.expectedWrap.classList.add('hidden');
        this.elements.expectedOutput.textContent = '';
    }

    clearManualInput() {
        this.elements.manualInput.value = '';
    }

    getManualInputValue() {
        return this.elements.manualInput.value.trim();
    }
}
