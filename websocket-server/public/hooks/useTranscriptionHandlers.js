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
                const newSentences = sentences.map((sentence, index) => ({
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
                
                return [...prev, ...newSentences];
            });
        }
        
        if (source.toLowerCase() === 'host') {
            setLiveTextHost('');
        } else {
            setLiveTextSpeaker('');
        }
    }, [setFinalizedSentences, setLiveTextHost, setLiveTextSpeaker, requestCorrection]);
    
    const handleLiveTranscription = useCallback((text, source) => {
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
        
        setFinalizedTranslations(prev => {
            const newTranslation = {
                text: trimmedText,
                source: source,
                timestamp: timestamp || new Date().toISOString(),
                id: Date.now() + Math.random()
            };
            return [...prev, newTranslation];
        });
        
        if (source.toLowerCase() === 'host') {
            setLiveTranslationHost('');
        } else {
            setLiveTranslationSpeaker('');
        }
    }, [setFinalizedTranslations, setLiveTranslationHost, setLiveTranslationSpeaker]);
    
    const handleLiveTranslation = useCallback((text, source) => {
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

    return {
        handleFinalTranscription,
        handleLiveTranscription,
        handleFinalTranslation,
        handleLiveTranslation,
        handleCorrectionResponse
    };
};
