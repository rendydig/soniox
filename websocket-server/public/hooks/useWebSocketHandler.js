import { useCallback } from 'https://esm.sh/preact@10.19.3/hooks';

export const useWebSocketHandler = ({
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
    handleLastPickup,
    handleLastPickupStatus,
    handleSessionState,
    handleConnection
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
            if (typeof handleConnection === 'function') {
                handleConnection();
            }
            return;
        }

        if (data.type === 'session_state') {
            if (typeof handleSessionState === 'function') {
                handleSessionState(data);
            }
            return;
        }

        if (data.type === 'transcription') {
            processMessage(data, data.type, handleFinalTranscription, handleLiveTranscription);
        } else if (data.type === 'translation') {
            processMessage(data, data.type, handleFinalTranslation, handleLiveTranslation);
        } else if (data.type === 'gemini_result') {
            if (typeof handleGeminiResult === 'function') {
                handleGeminiResult(data.text, data.mode, data.timestamp);
            }
        } else if (data.type === 'gemini_stream') {
            if (typeof handleGeminiStream === 'function') {
                handleGeminiStream(data.text, data.mode);
            }
        } else if (data.type === 'gemini_status') {
            if (typeof handleGeminiStatus === 'function') {
                handleGeminiStatus(data.status, data.mode, data.message);
            }
        } else if (data.type === 'screenshot') {
            if (typeof handleScreenshot === 'function') {
                handleScreenshot(data.image, data.timestamp);
            }
        } else if (data.type === 'clear_screenshots') {
            if (typeof handleClearScreenshots === 'function') {
                handleClearScreenshots();
            }
        } else if (data.type === 'bullet_points') {
            if (typeof handleBulletPoints === 'function') {
                handleBulletPoints(data.items || [], data.timestamp);
            }
        } else if (data.type === 'bullet_points_status') {
            if (typeof handleBulletPointsStatus === 'function') {
                handleBulletPointsStatus(data.status, data.message);
            }
        } else if (data.type === 'last_pickup') {
            if (typeof handleLastPickup === 'function') {
                handleLastPickup(data.text);
            }
        } else if (data.type === 'last_pickup_status') {
            if (typeof handleLastPickupStatus === 'function') {
                handleLastPickupStatus(data.status, data.message);
            }
        } else if (data.type === 'correction_response') {
            console.log('[WebSocket] Correction response:', data);
            handleCorrectionResponse(data);
        }
        // auto_reply_toggle / auto_reply_request are meant for the Python app and
        // are rebroadcast by the server; ignore them here.
    }, [
        processMessage,
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
        handleLastPickup,
        handleLastPickupStatus,
        handleSessionState,
        handleConnection
    ]);

    return handleMessage;
};