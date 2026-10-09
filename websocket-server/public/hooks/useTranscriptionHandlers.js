import { useCallback, useRef, useEffect } from 'https://esm.sh/preact@10.19.3/hooks';
import { splitIntoSentences } from '../utils.js';

export const useTranscriptionHandlers = ({
    setFinalizedSentences,
    setLiveTextHost,
    setLiveTextSpeaker,
    setFinalizedTranslations,
    setLiveTranslationHost,
    setLiveTranslationSpeaker,
    setCorrections,
    correctionEnabled,
    corrections,
    setGeminiResults,
    setGeminiStatus,
    setScreenshots,
    setBulletPoints,
    setBulletPointsStatus,
    wsManager
}) => {
    const correctionEnabledRef = useRef(correctionEnabled);
    const correctionsRef = useRef(corrections);
    const sentenceIdCounter = useRef(0);
    
    useEffect(() => {
        correctionEnabledRef.current = correctionEnabled;
    }, [correctionEnabled]);
    
    useEffect(() => {
        correctionsRef.current = corrections;
    }, [corrections]);

    const requestCorrection = useCallback((sentence) => {
        if (!wsManager.current || !wsManager.current.ws) return;
        
        const sentenceId = sentenceIdCounter.current++;
        const request = {
            type: 'correction_request',
            sentenceId: sentenceId,
            sentence: sentence
        };
        
        console.log('[DEBUG] Requesting correction for:', sentence);
        wsManager.current.ws.send(JSON.stringify(request));
    }, [wsManager]);

    /** Final transcription is handled by utilizing is_final: true */
    const handleFinalTranscription = useCallback((text, timestamp, source) => {
        if (!text || text.trim().length === 0) return;
        
        const trimmedText = text.trim();
        const isCorrectionEnabled = correctionEnabledRef.current;
        const currentCorrections = correctionsRef.current;
        
        const sentences = splitIntoSentences(trimmedText);
        
        if (sentences.length === 0) {
            setFinalizedSentences(prev => {
                const newSentence = {
                    text: trimmedText,
                    source: source,
                    timestamp: timestamp || new Date().toISOString(),
                    id: Date.now() + Math.random()
                };
                return [...prev, newSentence];
            });
        } else {
            setFinalizedSentences(prev => {
                let sentencesToProcess = [...sentences];
                let updatedPrev = [...prev];
                
                if (updatedPrev.length > 0 && sentencesToProcess.length > 0) {
                    const lastSentence = updatedPrev[updatedPrev.length - 1];
                    const lastChar = lastSentence.text.trim().slice(-1);
                    
                    if (lastChar !== '.' && lastChar !== '?' && lastChar !== '!') {
                        const mergedText = lastSentence.text + ' ' + sentencesToProcess[0];
                        updatedPrev[updatedPrev.length - 1] = {
                            ...lastSentence,
                            text: mergedText
                        };
                        
                        console.log('[DEBUG] Merged sentence:', mergedText);
                        
                        if (isCorrectionEnabled && !currentCorrections[mergedText]) {
                            requestCorrection(mergedText);
                        }
                        
                        sentencesToProcess = sentencesToProcess.slice(1);
                    }
                }
                
                const newSentences = sentencesToProcess.map((sentence, index) => ({
                    text: sentence,
                    source: source,
                    timestamp: timestamp || new Date().toISOString(),
                    id: Date.now() + Math.random() + index
                }));
                
                console.log('[DEBUG] Finalized sentences added:', newSentences);
                
                if (isCorrectionEnabled) {
                    newSentences.forEach(sentenceObj => {
                        if (!currentCorrections[sentenceObj.text]) {
                            requestCorrection(sentenceObj.text);
                        }
                    });
                }
                
                return [...updatedPrev, ...newSentences];
            });
        }
        
        if (source.toLowerCase() === 'host') {
            setLiveTextHost('');
        } else {
            setLiveTextSpeaker('');
        }
    }, [setFinalizedSentences, setLiveTextHost, setLiveTextSpeaker, requestCorrection]);
    
    /** Live transcription is handled by utilizing is_final: false */
    const handleLiveTranscription = useCallback((text, timestamp, source) => {
        if (!text || text.trim().length === 0) {
            if (source.toLowerCase() === 'host') {
                setLiveTextHost('');
            } else {
                setLiveTextSpeaker('');
            }
            return;
        }
        
        const trimmedText = text.trim();
        if (source.toLowerCase() === 'host') {
            setLiveTextHost(trimmedText);
        } else {
            setLiveTextSpeaker(trimmedText);
        }
        console.log('[DEBUG] Live text updated:', trimmedText, 'from', source);
    }, [setLiveTextHost, setLiveTextSpeaker]);
    
    const handleFinalTranslation = useCallback((text, timestamp, source) => {
        if (!text || text.trim().length === 0) return;
        
        const trimmedText = text.trim();
        const sentences = splitIntoSentences(trimmedText);
        
        if (sentences.length === 0) {
            setFinalizedTranslations(prev => {
                const newTranslation = {
                    text: trimmedText,
                    source: source,
                    timestamp: timestamp || new Date().toISOString(),
                    id: Date.now() + Math.random()
                };
                return [...prev, newTranslation];
            });
        } else {
            setFinalizedTranslations(prev => {
                let sentencesToProcess = [...sentences];
                let updatedPrev = [...prev];
                
                if (updatedPrev.length > 0 && sentencesToProcess.length > 0) {
                    const lastTranslation = updatedPrev[updatedPrev.length - 1];
                    const lastChar = lastTranslation.text.trim().slice(-1);
                    
                    if (lastChar !== '.' && lastChar !== '?' && lastChar !== '!') {
                        const mergedText = lastTranslation.text + ' ' + sentencesToProcess[0];
                        updatedPrev[updatedPrev.length - 1] = {
                            ...lastTranslation,
                            text: mergedText
                        };
                        
                        console.log('[DEBUG] Merged translation:', mergedText);
                        sentencesToProcess = sentencesToProcess.slice(1);
                    }
                }
                
                const newTranslations = sentencesToProcess.map((sentence, index) => ({
                    text: sentence,
                    source: source,
                    timestamp: timestamp || new Date().toISOString(),
                    id: Date.now() + Math.random() + index
                }));
                
                console.log('[DEBUG] Finalized translations added:', newTranslations);
                
                return [...updatedPrev, ...newTranslations];
            });
        }
        
        if (source.toLowerCase() === 'host') {
            setLiveTranslationHost('');
        } else {
            setLiveTranslationSpeaker('');
        }
    }, [setFinalizedTranslations, setLiveTranslationHost, setLiveTranslationSpeaker]);
    
    const handleLiveTranslation = useCallback((text, timestamp, source) => {
        if (!text || text.trim().length === 0) {
            if (source.toLowerCase() === 'host') {
                setLiveTranslationHost('');
            } else {
                setLiveTranslationSpeaker('');
            }
            return;
        }
        
        const trimmedText = text.trim();
        if (source.toLowerCase() === 'host') {
            setLiveTranslationHost(trimmedText);
        } else {
            setLiveTranslationSpeaker(trimmedText);
        }
        console.log('[DEBUG] Live translation updated:', trimmedText, 'from', source);
    }, [setLiveTranslationHost, setLiveTranslationSpeaker]);
    
    const handleCorrectionResponse = useCallback((data) => {
        setCorrections(prev => ({
            ...prev,
            [data.original]: {
                status: data.status,
                corrected: data.corrected
            }
        }));
        console.log('[DEBUG] Correction stored:', data.original, '->', data.status);
    }, [setCorrections]);

    /** Gemini manual translation / auto-reply result */
    const handleGeminiResult = useCallback((text, mode, timestamp) => {
        if (!text || text.trim().length === 0) return;

        setGeminiResults([{
            text: text.trim(),
            mode: mode || 'manual',
            timestamp: timestamp || new Date().toISOString(),
            id: Date.now() + Math.random()
        }]);
        setGeminiStatus('');
        console.log('[DEBUG] Gemini result replaced:', mode, text.slice(0, 80));
    }, [setGeminiResults, setGeminiStatus]);

    /** Gemini partial (streaming) result — update the live item, or start one. */
    const handleGeminiStream = useCallback((text, mode) => {
        if (typeof setGeminiResults !== 'function') return;
        const resolvedMode = mode || 'auto_reply';
        setGeminiResults(prev => {
            const last = prev[prev.length - 1];
            if (last && last.streaming && last.mode === resolvedMode) {
                return [...prev.slice(0, -1), { ...last, text: text || '' }];
            }
            return [{
                text: text || '',
                mode: resolvedMode,
                streaming: true,
                timestamp: new Date().toISOString(),
                id: Date.now() + Math.random()
            }];
        });
        console.log('[DEBUG] Gemini stream update:', resolvedMode, (text || '').length);
    }, [setGeminiResults]);

    /** Gemini progress / failure status */
    const handleGeminiStatus = useCallback((status, mode, message) => {
        if (status === 'started') {
            setGeminiStatus('Translating...');
        } else if (status === 'failed') {
            setGeminiStatus(message || 'Translation failed.');
        }
        console.log('[DEBUG] Gemini status:', status, mode);
    }, [setGeminiStatus]);

    /** Screenshot captured by the desktop app (ALT+SHIFT+K) — append to the gallery. */
    const handleScreenshot = useCallback((image, timestamp) => {
        if (!image || typeof setScreenshots !== 'function') return;

        setScreenshots(prev => [...prev, {
            image,
            timestamp: timestamp || new Date().toISOString(),
            id: Date.now() + Math.random()
        }]);
        console.log('[DEBUG] Screenshot appended');
    }, [setScreenshots]);

    /** Clear all captured screenshots (ALT+CTRL+SHIFT+K). */
    const handleClearScreenshots = useCallback(() => {
        if (typeof setScreenshots !== 'function') return;
        setScreenshots([]);
        console.log('[DEBUG] Screenshots cleared');
    }, [setScreenshots]);

    /** Rolling bullet-point list update from the Python app. */
    const handleBulletPoints = useCallback((items) => {
        if (typeof setBulletPoints !== 'function') return;
        setBulletPoints(Array.isArray(items) ? items : []);
        console.log('[DEBUG] Bullet points updated:', Array.isArray(items) ? items.length : 0);
    }, [setBulletPoints]);

    /** Bullet-points progress / failure status. */
    const handleBulletPointsStatus = useCallback((status, message) => {
        if (typeof setBulletPointsStatus !== 'function') return;
        if (status === 'started') {
            setBulletPointsStatus('Updating...');
        } else if (status === 'failed' || status === 'error') {
            setBulletPointsStatus(message || 'Update failed.');
        } else {
            setBulletPointsStatus('');
        }
        console.log('[DEBUG] Bullet points status:', status);
    }, [setBulletPointsStatus]);

    /** Restore the persisted session into the panes (only the provided setters apply). */
    const handleSessionState = useCallback((data) => {
        const now = Date.now();
        const toItems = (list, mapFn) => (Array.isArray(list) ? list.map((entry, i) => ({
            ...mapFn(entry),
            timestamp: entry.timestamp || new Date().toISOString(),
            id: now + i
        })) : []);

        if (typeof setFinalizedSentences === 'function') {
            setFinalizedSentences(toItems(data.transcriptions, (e) => ({ text: e.text, source: e.source })));
        }
        if (typeof setFinalizedTranslations === 'function') {
            setFinalizedTranslations(toItems(data.translations, (e) => ({ text: e.text, source: e.source })));
        }
        if (typeof setGeminiResults === 'function') {
            setGeminiResults(toItems(data.gemini_results, (e) => ({ text: e.text, mode: e.mode || 'manual' })));
        }
        if (typeof setScreenshots === 'function') {
            setScreenshots(toItems(data.screenshots || [], (image) => ({ image })));
        }
        if (typeof setBulletPoints === 'function') {
            setBulletPoints(Array.isArray(data.bullets) ? data.bullets : []);
        }
        console.log('[DEBUG] Session state applied');
    }, [setFinalizedSentences, setFinalizedTranslations, setGeminiResults, setScreenshots, setBulletPoints]);

    return {
        handleFinalTranscription,
        handleLiveTranscription,
        handleFinalTranslation,
        handleLiveTranslation,
        handleCorrectionResponse,
        handleGeminiResult,
        handleGeminiStream,
        handleGeminiStatus,
        handleScreenshot,
        handleClearScreenshots,
        handleBulletPoints,
        handleBulletPointsStatus,
        handleSessionState
    };
};
