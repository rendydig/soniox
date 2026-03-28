/**
 * Audio Cache Manager
 * Handles loading and playing cached audio files with fallback to TTS
 */
class AudioCacheManager {
    constructor() {
        this.audioMapping = null;
        this.audioCache = new Map();
        this.currentAudio = null;
        this.mappingFile = null;
        this.jsonBaseName = null;
    }

    /**
     * Initialize the audio cache manager with a conversation file
     */
    async initialize(conversationFile) {
        const mappingFile = conversationFile.replace('.json', '-audio-mapping.json');
        this.mappingFile = mappingFile;
        
        // Extract base name without extension for directory path
        this.jsonBaseName = conversationFile.replace('.json', '');
        
        try {
            const response = await fetch(`./assets/${encodeURIComponent(mappingFile)}`);
            if (response.ok) {
                this.audioMapping = await response.json();
                console.log('[AudioCache] Loaded audio mapping:', Object.keys(this.audioMapping).length, 'entries');
                console.log('[AudioCache] Using wav directory: wav/' + this.jsonBaseName);
                return true;
            } else {
                console.log('[AudioCache] No audio mapping found, will use TTS fallback');
                return false;
            }
        } catch (error) {
            console.log('[AudioCache] Failed to load audio mapping, will use TTS fallback:', error.message);
            return false;
        }
    }

    /**
     * Generate filename from text (must match server-side logic)
     */
    generateFilename(text) {
        const hash = text
            .toLowerCase()
            .replace(/[^a-z0-9\s]/g, '')
            .replace(/\s+/g, '_')
            .substring(0, 50);
        
        let simpleHash = 0;
        for (let i = 0; i < text.length; i++) {
            simpleHash = ((simpleHash << 5) - simpleHash) + text.charCodeAt(i);
            simpleHash = simpleHash & simpleHash;
        }
        
        return `${hash}_${Math.abs(simpleHash)}.wav`;
    }

    /**
     * Check if cached audio exists for the given text
     */
    hasCachedAudio(text) {
        if (!this.audioMapping) {
            return false;
        }
        return text in this.audioMapping;
    }

    /**
     * Get the audio file path for the given text
     */
    getAudioPath(text) {
        if (!this.audioMapping || !(text in this.audioMapping)) {
            return null;
        }
        return `./assets/wav/${this.jsonBaseName}/${this.audioMapping[text]}`;
    }

    /**
     * Preload audio file into memory
     */
    async preloadAudio(text) {
        const audioPath = this.getAudioPath(text);
        if (!audioPath) {
            return false;
        }

        if (this.audioCache.has(text)) {
            return true;
        }

        try {
            const audio = new Audio(audioPath);
            await new Promise((resolve, reject) => {
                audio.addEventListener('canplaythrough', resolve, { once: true });
                audio.addEventListener('error', reject, { once: true });
                audio.load();
            });
            
            this.audioCache.set(text, audio);
            console.log('[AudioCache] Preloaded:', text.substring(0, 50));
            return true;
        } catch (error) {
            console.log('[AudioCache] Failed to preload:', error.message);
            return false;
        }
    }

    /**
     * Play cached audio or fallback to TTS
     */
    async playAudio(text, { onEnd, onUnavailable, useTTSFallback = true }) {
        // Stop any currently playing audio
        this.stop();

        // Try to play cached audio first
        if (this.hasCachedAudio(text)) {
            try {
                console.log('[AudioCache] Playing cached audio for:', text.substring(0, 50));
                
                let audio = this.audioCache.get(text);
                if (!audio) {
                    audio = new Audio(this.getAudioPath(text));
                    this.audioCache.set(text, audio);
                }

                this.currentAudio = audio;
                
                audio.onended = () => {
                    console.log('[AudioCache] Playback ended');
                    this.currentAudio = null;
                    if (typeof onEnd === 'function') {
                        onEnd();
                    }
                };

                audio.onerror = (error) => {
                    console.log('[AudioCache] Playback error:', error);
                    this.currentAudio = null;
                    
                    // Fallback to TTS if enabled
                    if (useTTSFallback) {
                        console.log('[AudioCache] Falling back to TTS');
                        this.playTTS(text, { onEnd, onUnavailable });
                    } else if (typeof onUnavailable === 'function') {
                        onUnavailable();
                    }
                };

                await audio.play();
                return true;
            } catch (error) {
                console.log('[AudioCache] Failed to play cached audio:', error.message);
                
                // Fallback to TTS if enabled
                if (useTTSFallback) {
                    console.log('[AudioCache] Falling back to TTS');
                    this.playTTS(text, { onEnd, onUnavailable });
                    return true;
                } else if (typeof onUnavailable === 'function') {
                    onUnavailable();
                    return false;
                }
            }
        }

        // No cached audio, use TTS if enabled
        if (useTTSFallback) {
            console.log('[AudioCache] No cached audio, using TTS for:', text.substring(0, 50));
            this.playTTS(text, { onEnd, onUnavailable });
            return true;
        } else {
            console.log('[AudioCache] No cached audio and TTS fallback disabled');
            if (typeof onUnavailable === 'function') {
                onUnavailable();
            }
            return false;
        }
    }

    /**
     * Play text using browser TTS
     */
    playTTS(text, { onEnd, onUnavailable }) {
        if (!('speechSynthesis' in window) || typeof SpeechSynthesisUtterance === 'undefined') {
            console.log('[TTS] Speech synthesis not available');
            if (typeof onUnavailable === 'function') {
                onUnavailable();
            }
            return;
        }

        console.log('[TTS] Starting speech:', text.substring(0, 50) + '...');
        window.speechSynthesis.cancel();
        
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'en-US';
        utterance.rate = 0.96;
        
        utterance.onend = () => {
            console.log('[TTS] Speech ended successfully');
            if (typeof onEnd === 'function') {
                onEnd();
            }
        };
        
        utterance.onerror = (event) => {
            console.log('[TTS] Speech error:', event.error);
            if (typeof onUnavailable === 'function') {
                onUnavailable();
            }
        };
        
        window.speechSynthesis.speak(utterance);
    }

    /**
     * Stop any currently playing audio
     */
    stop() {
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio.currentTime = 0;
            this.currentAudio = null;
        }
        window.speechSynthesis.cancel();
    }

    /**
     * Clear the audio cache
     */
    clearCache() {
        this.audioCache.clear();
        this.currentAudio = null;
    }

    /**
     * Get cache statistics
     */
    getStats() {
        return {
            mappingLoaded: this.audioMapping !== null,
            totalMappings: this.audioMapping ? Object.keys(this.audioMapping).length : 0,
            cachedAudios: this.audioCache.size,
            mappingFile: this.mappingFile
        };
    }
}
