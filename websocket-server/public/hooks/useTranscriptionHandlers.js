import { useCallback, useRef, useEffect } from 'https://esm.sh/preact@10.19.3/hooks';
import { splitIntoSentences } from '../utils.js';

// Only the last few lines are ever rendered, but the state arrays would grow for
// the whole session; cap them to match the backend's session retention
// (SESSION_MAX_TRANSCRIPT_LINES = 500) so a multi-hour run stays bounded.
const MAX_FINALIZED = 500;

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
    setBulletCountdown,
    setBulletLocks,
    setSpeakerProfile,
    setLastPickup,
    setLastPickupStatus,
    setLastPickupAuto,
    setSummary,
    setSummaryStatus,
    setBrief,
    setGaps,
    setRoadmap,
    setBriefConfirmed,
    setConsultingStatus,
    setObjectives,
    setObjectiveLocks,
    setObjectiveActive,
    setObjectiveHistory,
    setObjectiveSatisfied,
    setObjectiveStatus,
    setPurposeState,
    wsManager
}) => {
    const correctionEnabledRef = useRef(correctionEnabled);
    const correctionsRef = useRef(corrections);
    const sentenceIdCounter = useRef(0);
    // Pending auto-clear for a transient bullet-points notice ("Nothing new yet").
    const noticeTimer = useRef(null);
    // Separate timer for the summary tab's "Nothing to summarize yet" notice, so
    // the two notices can't clobber each other's auto-clear.
    const summaryNoticeTimer = useRef(null);
    // And one for the Consulting tab's transient `no_input` notice.
    const consultingNoticeTimer = useRef(null);
    // And one for the Objectives tab's transient notices.
    const objectiveNoticeTimer = useRef(null);
    
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
                return [...prev, newSentence].slice(-MAX_FINALIZED);
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
                
                return [...updatedPrev, ...newSentences].slice(-MAX_FINALIZED);
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
                return [...prev, newTranslation].slice(-MAX_FINALIZED);
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
                
                return [...updatedPrev, ...newTranslations].slice(-MAX_FINALIZED);
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

    /** Rolling bullet-point list + speaker (KYC) profile update from the Python app. */
    const handleBulletPoints = useCallback((items, speaker, locks) => {
        if (typeof setBulletPoints === 'function') {
            setBulletPoints(Array.isArray(items) ? items : []);
        }
        // Older payloads carry no profile (or a null one) — leave it untouched.
        if (speaker && typeof speaker === 'object' && typeof setSpeakerProfile === 'function') {
            setSpeakerProfile(speaker);
        }
        // Parallel lock flags (index-aligned with the list); absent on older payloads.
        if (typeof setBulletLocks === 'function') {
            setBulletLocks(Array.isArray(locks) ? locks.map((l) => l === true) : []);
        }
        console.log('[DEBUG] Bullet points updated:', Array.isArray(items) ? items.length : 0);
    }, [setBulletPoints, setSpeakerProfile, setBulletLocks]);

    /** Auto-flush countdown: absolute deadline from the backend timer (0/auto off = hide). */
    const handleBulletPointsCountdown = useCallback((auto, nextFlushAt, intervalMs) => {
        if (typeof setBulletCountdown !== 'function') return;
        const at = Number(nextFlushAt) || 0;
        setBulletCountdown(auto && at > 0
            ? { at, intervalMs: Number(intervalMs) || 0 }
            : null);
        console.log('[DEBUG] Bullet countdown:', auto, at);
    }, [setBulletCountdown]);

    /** Bullet-points progress / failure status. */
    const handleBulletPointsStatus = useCallback((status, message) => {
        if (typeof setBulletPointsStatus !== 'function') return;
        if (noticeTimer.current) {
            clearTimeout(noticeTimer.current);
            noticeTimer.current = null;
        }
        if (status === 'started') {
            setBulletPointsStatus('Updating...');
        } else if (status === 'failed' || status === 'error') {
            setBulletPointsStatus(message || 'Update failed.');
        } else if (status === 'no_new') {
            // "Fetch new" found nothing buffered: show it briefly, then clear.
            setBulletPointsStatus(message || 'Nothing new yet');
            noticeTimer.current = setTimeout(() => setBulletPointsStatus(''), 2500);
        } else {
            setBulletPointsStatus('');
        }
        console.log('[DEBUG] Bullet points status:', status);
    }, [setBulletPointsStatus]);

    /** Latest picked-up topic/intent from the Python app (Indonesian sentence). */
    const handleLastPickup = useCallback((text) => {
        if (typeof setLastPickup !== 'function') return;
        setLastPickup(typeof text === 'string' ? text : '');
        console.log('[DEBUG] Last pickup updated:', typeof text === 'string' ? text.length : 0);
    }, [setLastPickup]);

    /** Last-pickup progress / failure status. */
    const handleLastPickupStatus = useCallback((status, message) => {
        if (typeof setLastPickupStatus !== 'function') return;
        if (status === 'started') {
            setLastPickupStatus('Mendengarkan...');
        } else if (status === 'failed' || status === 'error') {
            setLastPickupStatus(message || 'Gagal memperbarui.');
        } else {
            setLastPickupStatus('');
        }
        console.log('[DEBUG] Last pickup status:', status);
    }, [setLastPickupStatus]);

    /** Whole-session summary text from the Python app (structured markdown). */
    const handleSummary = useCallback((text) => {
        if (typeof setSummary !== 'function') return;
        setSummary(typeof text === 'string' ? text : '');
        console.log('[DEBUG] Summary updated:', typeof text === 'string' ? text.length : 0);
    }, [setSummary]);

    /** Summary progress / failure status. */
    const handleSummaryStatus = useCallback((status, message) => {
        if (typeof setSummaryStatus !== 'function') return;
        if (summaryNoticeTimer.current) {
            clearTimeout(summaryNoticeTimer.current);
            summaryNoticeTimer.current = null;
        }
        if (status === 'started') {
            setSummaryStatus('Summarizing…');
        } else if (status === 'failed' || status === 'error') {
            setSummaryStatus(message || 'Summarization failed.');
        } else if (status === 'no_input') {
            // Summarize found nothing to work with: show it briefly, then clear.
            setSummaryStatus(message || 'Nothing to summarize yet');
            summaryNoticeTimer.current = setTimeout(() => setSummaryStatus(''), 2500);
        } else {
            setSummaryStatus('');
        }
        console.log('[DEBUG] Summary status:', status);
    }, [setSummaryStatus]);

    /** Consulting section text from the Python app (brief / gaps / roadmap). */
    const handleConsulting = useCallback((mode, text, confirmed) => {
        const value = typeof text === 'string' ? text : '';
        if (mode === 'brief') {
            if (typeof setBrief === 'function') setBrief(value);
            // Only the brief carries a confirmation; a (re)draft clears it.
            if (typeof setBriefConfirmed === 'function') setBriefConfirmed(confirmed === true);
        } else if (mode === 'gaps') {
            if (typeof setGaps === 'function') setGaps(value);
        } else if (mode === 'roadmap') {
            if (typeof setRoadmap === 'function') setRoadmap(value);
        }
        console.log('[DEBUG] Consulting updated:', mode, value.length);
    }, [setBrief, setGaps, setRoadmap, setBriefConfirmed]);

    /** Consulting progress / failure / notice status (keyed to one section). */
    const handleConsultingStatus = useCallback((mode, status, message) => {
        if (typeof setConsultingStatus !== 'function') return;
        if (consultingNoticeTimer.current) {
            clearTimeout(consultingNoticeTimer.current);
            consultingNoticeTimer.current = null;
        }
        if (status === 'started') {
            setConsultingStatus({ mode, status: 'started', message: '' });
        } else if (status === 'failed' || status === 'error') {
            setConsultingStatus({ mode, status: 'error', message: message || 'Call failed.' });
        } else if (status === 'no_input') {
            // Nothing to work with: show it briefly, then clear.
            setConsultingStatus({ mode, status: 'no_input', message: message || 'Nothing to work with yet' });
            consultingNoticeTimer.current = setTimeout(
                () => setConsultingStatus({ mode: '', status: '', message: '' }), 2500);
        } else {
            setConsultingStatus({ mode: '', status: '', message: '' });
        }
        console.log('[DEBUG] Consulting status:', mode, status);
    }, [setConsultingStatus]);

    /** Session objectives (list, parallel locks and the resolved focus). */
    const handleObjectives = useCallback((items, locks, active, satisfied) => {
        if (typeof setObjectives === 'function') {
            setObjectives(Array.isArray(items) ? items : []);
        }
        if (typeof setObjectiveLocks === 'function') {
            setObjectiveLocks(Array.isArray(locks) ? locks.map((l) => l === true) : []);
        }
        if (typeof setObjectiveActive === 'function') {
            setObjectiveActive(active && typeof active === 'object' ? active : {});
        }
        if (typeof setObjectiveSatisfied === 'function') {
            setObjectiveSatisfied(Array.isArray(satisfied) ? satisfied : []);
        }
        console.log('[DEBUG] Objectives updated:', Array.isArray(items) ? items.length : 0);
    }, [setObjectives, setObjectiveLocks, setObjectiveActive, setObjectiveSatisfied]);

    /** One committed transition appended to the history timeline. */
    const handleObjectivesHistory = useCallback((entry) => {
        if (typeof setObjectiveHistory !== 'function') return;
        if (!entry || typeof entry !== 'object') return;
        setObjectiveHistory(prev => {
            const next = [...(Array.isArray(prev) ? prev : []), entry];
            // The backend caps the timeline (OBJECTIVE_MAX_HISTORY = 200); match
            // it so a long session stays bounded here too.
            return next.length > 200 ? next.slice(next.length - 200) : next;
        });
        console.log('[DEBUG] Objective history appended:', entry.text);
    }, [setObjectiveHistory]);

    /** Objective-tracker progress / failure / notice status. */
    const handleObjectivesStatus = useCallback((status, message) => {
        if (typeof setObjectiveStatus !== 'function') return;
        if (objectiveNoticeTimer.current) {
            clearTimeout(objectiveNoticeTimer.current);
            objectiveNoticeTimer.current = null;
        }
        if (status === 'started') {
            setObjectiveStatus('Tracking…');
        } else if (status === 'failed' || status === 'error') {
            setObjectiveStatus(message || 'Objective prediction failed.');
        } else if (status === 'no_input') {
            // Nothing to add / nothing to predict: show it briefly, then clear.
            setObjectiveStatus(message || 'Nothing to track yet');
            objectiveNoticeTimer.current = setTimeout(() => setObjectiveStatus(''), 2500);
        } else {
            setObjectiveStatus('');
        }
        console.log('[DEBUG] Objectives status:', status);
    }, [setObjectiveStatus]);

    /** Selected Purpose + "I am:" role pushed by the desktop app. */
    const handlePurposeState = useCallback((purpose, role) => {
        if (typeof setPurposeState !== 'function') return;
        setPurposeState({ purpose, role });
        console.log('[DEBUG] Purpose state:', purpose, role);
    }, [setPurposeState]);

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
        if (typeof setBulletLocks === 'function') {
            setBulletLocks(
                Array.isArray(data.bullet_locks) ? data.bullet_locks.map((l) => l === true) : []
            );
        }
        if (typeof setSpeakerProfile === 'function') {
            setSpeakerProfile(
                typeof data.speaker === 'object' && data.speaker ? data.speaker : {}
            );
        }
        if (typeof setLastPickup === 'function') {
            setLastPickup(typeof data.last_pickup === 'string' ? data.last_pickup : '');
        }
        if (typeof setSummary === 'function') {
            setSummary(typeof data.summary === 'string' ? data.summary : '');
        }
        if (typeof setBrief === 'function') {
            setBrief(typeof data.brief === 'string' ? data.brief : '');
        }
        if (typeof setGaps === 'function') {
            setGaps(typeof data.gaps === 'string' ? data.gaps : '');
        }
        if (typeof setRoadmap === 'function') {
            setRoadmap(typeof data.roadmap === 'string' ? data.roadmap : '');
        }
        if (typeof setBriefConfirmed === 'function') {
            const meta = data.brief_meta;
            setBriefConfirmed(!!(meta && typeof meta === 'object' && meta.confirmed === true));
        }
        if (typeof setConsultingStatus === 'function') {
            setConsultingStatus({ mode: '', status: '', message: '' });
        }
        if (typeof setObjectives === 'function') {
            setObjectives(Array.isArray(data.objectives) ? data.objectives : []);
        }
        if (typeof setObjectiveLocks === 'function') {
            setObjectiveLocks(
                Array.isArray(data.objective_locks)
                    ? data.objective_locks.map((l) => l === true)
                    : []
            );
        }
        if (typeof setObjectiveHistory === 'function') {
            setObjectiveHistory(Array.isArray(data.objective_history) ? data.objective_history : []);
        }
        if (typeof setObjectiveActive === 'function') {
            // Derived backend-side (a locked objective beats the prediction), so
            // the pane never re-implements the precedence rule.
            setObjectiveActive(
                data.objective_active && typeof data.objective_active === 'object'
                    ? data.objective_active
                    : {}
            );
        }
        if (typeof setObjectiveSatisfied === 'function') {
            // Index-based and derived backend-side, same as the focus.
            setObjectiveSatisfied(
                Array.isArray(data.objective_satisfied) ? data.objective_satisfied : []
            );
        }
        if (typeof setObjectiveStatus === 'function') {
            setObjectiveStatus('');
        }
        if (typeof setLastPickupAuto === 'function' && typeof data.last_pickup_auto === 'boolean') {
            setLastPickupAuto(data.last_pickup_auto);
        }
        console.log('[DEBUG] Session state applied');
    }, [setFinalizedSentences, setFinalizedTranslations, setGeminiResults, setScreenshots, setBulletPoints, setBulletLocks, setSpeakerProfile, setLastPickup, setSummary, setBrief, setGaps, setRoadmap, setBriefConfirmed, setConsultingStatus, setObjectives, setObjectiveLocks, setObjectiveHistory, setObjectiveActive, setObjectiveSatisfied, setObjectiveStatus, setLastPickupAuto]);

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
        handleBulletPointsCountdown,
        handleLastPickup,
        handleLastPickupStatus,
        handleSummary,
        handleSummaryStatus,
        handleConsulting,
        handleConsultingStatus,
        handleObjectives,
        handleObjectivesHistory,
        handleObjectivesStatus,
        handlePurposeState,
        handleSessionState
    };
};
