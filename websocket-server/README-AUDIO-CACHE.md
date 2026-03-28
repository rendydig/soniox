# Audio Cache System for Roleplay Player

This system fetches audio from the Kyutai Pocket TTS API, caches it locally as WAV files, and uses cached audio in the roleplay game with automatic fallback to browser TTS.

## Architecture

### Components

1. **`fetch-tts-audio.js`** - Node.js script to fetch and cache audio files
2. **`audio-cache-manager.js`** - Browser-side manager for cached audio playback
3. **`roleplay-player.js`** - Updated to use cached audio with TTS fallback

### Directory Structure

```
websocket-server/
├── fetch-tts-audio.js          # Audio fetching script
├── public/
│   ├── assets/
│   │   ├── english-1.json      # Conversation data
│   │   ├── english-1-audio-mapping.json  # Generated mapping file
│   │   └── wav/                # Cached audio files
│   │       ├── good_morning_how_are_you_today_and_are_you_r_123456.wav
│   │       └── ...
│   ├── audio-cache-manager.js  # Audio cache manager
│   └── roleplay-player.js      # Updated player
```

## Usage

### Step 1: Fetch and Cache Audio Files

Run the Node.js script to fetch audio for all dialogues in a conversation file:

```bash
cd websocket-server
node fetch-tts-audio.js english-1.json
```

**What it does:**
- Reads the conversation JSON file
- Extracts all English text from dialogues
- Fetches audio from the TTS API for each text
- Saves audio as WAV files in `public/assets/wav/`
- Creates a mapping file (e.g., `english-1-audio-mapping.json`)
- Skips already cached files (idempotent)

**Options:**
```bash
# Process a different conversation file
node fetch-tts-audio.js english-2.json

# Default is english-1.json if no argument provided
node fetch-tts-audio.js
```

**Output:**
```
Loading conversation file: english-1.json
Found 30 dialogue entries
Output directory: /path/to/public/assets/wav

[1/30] Fetching: "Good morning. How are you today, and are you ready for..."
[1/30] ✓ Saved: good_morning_how_are_you_today_and_are_you_r_123456.wav (45678 bytes)
[2/30] ✓ Already cached: good_morning_i_am_doing_well_thank_you_and_ye_234567.wav
...

============================================================
SUMMARY
============================================================
Total dialogues: 30
Successfully processed: 30
Already cached: 15
Failed: 0
Mapping saved to: english-1-audio-mapping.json
============================================================
```

### Step 2: Use in Roleplay Player

The roleplay player automatically uses cached audio:

1. **Open the player:** `http://localhost:3000/roleplay-player.html?file=english-1.json`
2. **Audio playback priority:**
   - First: Try to play cached WAV file
   - Fallback: Use browser TTS if cached audio fails
3. **Console logs show which method is used:**
   ```
   [AudioCache] Loaded audio mapping: 30 entries
   [AudioCache] Playing cached audio for: Good morning. How are you...
   ```

### Step 3: Monitor Cache Status

Check the browser console for cache statistics:

```javascript
// The player logs cache stats on load:
[AudioCache] Stats: {
  mappingLoaded: true,
  totalMappings: 30,
  cachedAudios: 5,
  mappingFile: "english-1-audio-mapping.json"
}
```

## Features

### Automatic Fallback
- If cached audio is missing or fails to load, automatically falls back to browser TTS
- No interruption to the user experience

### Idempotent Fetching
- Running `fetch-tts-audio.js` multiple times won't re-download existing files
- Only fetches missing audio files

### Rate Limiting
- 1-second delay between API requests to avoid rate limiting
- Configurable in `fetch-tts-audio.js` (DELAY_BETWEEN_REQUESTS)

### Filename Generation
- Generates safe, unique filenames from text content
- Uses text normalization + hash for uniqueness
- Same algorithm on both server and client sides

## Configuration

### TTS API Settings

Edit `fetch-tts-audio.js` to customize:

```javascript
const TTS_API_URL = 'https://kyutaipockettts6ylex2y4-kyutai-pocket-tts.functions.fnc.par.scw.cloud/tts';
const VOICE = 'vera';  // Change voice here
const DELAY_BETWEEN_REQUESTS = 1000;  // Milliseconds between requests
```

### Audio Cache Manager Settings

Edit `audio-cache-manager.js` to customize:

```javascript
// In playAudio method, set useTTSFallback
this.audioCacheManager.playAudio(text, {
    onEnd: () => { /* ... */ },
    onUnavailable: () => { /* ... */ },
    useTTSFallback: true  // Set to false to disable TTS fallback
});
```

## Troubleshooting

### Audio files not playing

1. Check browser console for errors
2. Verify WAV files exist in `public/assets/wav/`
3. Check mapping file exists (e.g., `english-1-audio-mapping.json`)
4. Ensure web server is serving static files correctly

### Fetch script fails

1. Check internet connection
2. Verify TTS API is accessible
3. Check for rate limiting (increase DELAY_BETWEEN_REQUESTS)
4. Ensure write permissions for `public/assets/wav/` directory

### Missing audio for some dialogues

1. Re-run the fetch script: `node fetch-tts-audio.js english-1.json`
2. Check the summary for failed entries
3. Review error messages in console output

## API Details

### Kyutai Pocket TTS API

**Endpoint:** `https://kyutaipockettts6ylex2y4-kyutai-pocket-tts.functions.fnc.par.scw.cloud/tts`

**Method:** POST

**Content-Type:** multipart/form-data

**Form Fields:**
- `text`: The text to convert to speech
- `voice_url`: Voice identifier (e.g., "vera")

**Response:** WAV audio file (binary)

## File Formats

### Audio Mapping JSON

```json
{
  "Good morning. How are you today, and are you ready for a busy schedule?": "good_morning_how_are_you_today_and_are_you_r_123456.wav",
  "Good morning. I am doing well, thank you, and yes, I am ready to get started.": "good_morning_i_am_doing_well_thank_you_and_ye_234567.wav"
}
```

### Conversation JSON

Standard format with `dialogue` array:

```json
{
  "title": "Daily Business Conversation",
  "dialogue": [
    {
      "turn": 1,
      "speaker": "Boss",
      "english": "Good morning. How are you today?",
      "indonesian": "Selamat pagi. Bagaimana kabarmu?"
    }
  ]
}
```

## Performance

### Cache Benefits
- **Faster playback:** Cached audio loads instantly vs. TTS synthesis delay
- **Consistent quality:** Same voice and pronunciation every time
- **Offline capability:** Works without internet once cached
- **Reduced browser load:** No TTS processing required

### Storage Requirements
- Average WAV file: ~40-80 KB per dialogue line
- 30-line conversation: ~1.5-2.5 MB total
- Mapping file: ~2-5 KB

## Development

### Adding New Conversation Files

1. Create new JSON file: `public/assets/your-conversation.json`
2. Fetch audio: `node fetch-tts-audio.js your-conversation.json`
3. Open player: `http://localhost:3000/roleplay-player.html?file=your-conversation.json`

### Testing Without Cache

To test TTS fallback behavior:

1. Rename or delete the mapping file temporarily
2. Reload the player
3. It will use browser TTS for all dialogues

### Clearing Cache

```bash
# Remove all cached audio files
rm -rf public/assets/wav/*.wav

# Remove all mapping files
rm -rf public/assets/*-audio-mapping.json

# Re-fetch everything
node fetch-tts-audio.js english-1.json
```

## Future Enhancements

- [ ] Support multiple voices per conversation
- [ ] Batch processing for multiple conversation files
- [ ] Progress bar during fetching
- [ ] Audio quality/format options (MP3, OGG)
- [ ] Preloading next dialogue audio for smoother transitions
- [ ] Cache expiration and refresh mechanism
- [ ] Admin UI for managing cached audio
