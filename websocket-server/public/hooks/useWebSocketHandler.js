import { useCallback } from 'https://esm.sh/preact@10.19.3/hooks';

export const useWebSocketHandler = ({
    handleFinalTranscription,
    handleLiveTranscription,
    handleFinalTranslation,
    handleLiveTranslation,
    handleCorrectionResponse
}) => {
    const handleMessage = useCallback((data) => {
        if (data.type === 'connection') {
            console.log('[WebSocket]', data.message);
            return;
        }

        if (data.type === 'transcription') {
            console.log('[WebSocket]', data);
            const source = data.input_source || 'Unknown';
            if (data.is_final) {
                console.log('[DEBUG] Final transcription:', data.text, 'from', source);
                handleFinalTranscription(data.text, data.timestamp, source);
            } else {
                console.log('[DEBUG] Non-final transcription:', data.text, 'from', source);
                handleLiveTranscription(data.text, source);
            }
        }
        
        if (data.type === 'translation') {
            console.log('[WebSocket]', data);
            const source = data.input_source || 'Unknown';
            if (data.is_final) {
                console.log('[DEBUG] Final translation:', data.text, 'from', source);
                handleFinalTranslation(data.text, data.timestamp, source);
            } else {
                console.log('[DEBUG] Non-final translation:', data.text, 'from', source);
                handleLiveTranslation(data.text, source);
            }
        }
        
        if (data.type === 'correction_response') {
            console.log('[WebSocket] Correction response:', data);
            handleCorrectionResponse(data);
        }
    }, [
        handleFinalTranscription,
        handleLiveTranscription,
        handleFinalTranslation,
        handleLiveTranslation,
        handleCorrectionResponse
    ]);

    return handleMessage;
};