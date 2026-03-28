#!/bin/bash

# Audio Cache Script for Roleplay Conversations
# Usage: ./cache-audio.sh [conversation-file.json]

set -e

CONVERSATION_FILE="${1:-english-1.json}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WAV_DIR="$SCRIPT_DIR/public/assets/wav"

echo "=========================================="
echo "Audio Cache Script"
echo "=========================================="
echo "Conversation file: $CONVERSATION_FILE"
echo "Output directory: $WAV_DIR"
echo ""

# Create wav directory if it doesn't exist
mkdir -p "$WAV_DIR"

# Check if Node.js is available
if ! command -v node &> /dev/null; then
    echo "Error: Node.js is not installed or not in PATH"
    exit 1
fi

# Check if conversation file exists
if [ ! -f "$SCRIPT_DIR/public/assets/$CONVERSATION_FILE" ]; then
    echo "Error: Conversation file not found: $SCRIPT_DIR/public/assets/$CONVERSATION_FILE"
    exit 1
fi

# Run the fetch script
echo "Starting audio fetch process..."
echo ""
node "$SCRIPT_DIR/fetch-tts-audio.js" "$CONVERSATION_FILE"

echo ""
echo "=========================================="
echo "Audio caching complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Start your web server if not already running"
echo "2. Open: http://localhost:3000/roleplay-player.html?file=$CONVERSATION_FILE"
echo "3. Check browser console for cache statistics"
echo ""
