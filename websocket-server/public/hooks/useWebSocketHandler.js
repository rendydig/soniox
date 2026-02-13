import { useCallback } from 'https://esm.sh/preact@10.19.3/hooks';

export const useWebSocketHandler = ({
    handleFinalTranscription,
    handleLiveTranscription,
    handleFinalTranslation,
    handleLiveTranslation,
    handleCorrectionResponse
}) => {
    const processMessage = useCallback((data, type, finalHandler, liveHandler) => {
        console.log('[WebSocket]', data);
        const source = data.input_source || 'Unknown';
        const handler = data.is_final ? finalHandler : liveHandler;
        console.log(`[DEBUG] ${data.is_final ? 'Final' : 'Non-final'} ${type}:`, data.text, 'from', source);
        console.log(`[DEBUG] text:`, data.text);
        handler(data.text, data.is_final ? data.timestamp : undefined, source);
    }, []);

    const handleMessage = useCallback((data) => {
        if (data.type === 'connection') {
            console.log('[WebSocket]', data.message);
            return;
        }

        if (data.type === 'transcription') {
            processMessage(data, data.type, handleFinalTranscription, handleLiveTranscription);
        } else if (data.type === 'translation') {
            processMessage(data, data.type, handleFinalTranslation, handleLiveTranslation);
        } else if (data.type === 'correction_response') {
            console.log('[WebSocket] Correction response:', data);
            handleCorrectionResponse(data);
        }
    }, [
        processMessage,
        handleFinalTranscription,
        handleLiveTranscription,
        handleFinalTranslation,
        handleLiveTranslation,
        handleCorrectionResponse
    ]);

    return handleMessage;
};