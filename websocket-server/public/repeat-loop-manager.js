export class RepeatLoopManager {
    constructor(player) {
        this.player = player;
        this.repeatLoopActive = false;
        this.repeatLoopStart = 0;
        this.repeatLoopEnd = 0;
        this.repeatLoopDelaying = false;
        this.repeatLoopDelayTimeout = null;
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
            this.player.audioPlayer.currentTime = start;
            document.querySelectorAll('.subtitle-repeat-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            buttonElement.classList.add('active');
        }
    }

    checkRepeatLoop() {
        if (this.repeatLoopActive && !this.repeatLoopDelaying && this.player.audioPlayer.currentTime >= this.repeatLoopEnd) {
            this.repeatLoopDelaying = true;
            this.player.audioPlayer.pause();
            
            this.repeatLoopDelayTimeout = setTimeout(() => {
                this.player.audioPlayer.currentTime = this.repeatLoopStart;
                this.player.audioPlayer.play();
                this.repeatLoopDelaying = false;
            }, 2000);
        }
    }
}
