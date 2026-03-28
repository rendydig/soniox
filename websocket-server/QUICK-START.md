# Quick Start Guide - Audio Cache System

## ✅ Setup Complete!

Your audio cache system is now ready to use. All English dialogues from `english-1.json` have been converted to WAV files and cached locally.

## 🎯 How to Use

### 1. Start the Web Server

```bash
cd websocket-server
node server.js
```

### 2. Open the Roleplay Player

Open your browser and navigate to:
```
http://localhost:3000/roleplay-player.html?file=english-1.json
```

### 3. What Happens Now?

**Before (without cache):**
- Browser TTS synthesizes speech in real-time
- Variable quality and speed
- Requires internet connection for some browsers

**Now (with cache):**
- Pre-recorded WAV files play instantly
- Consistent voice quality (Kyutai Pocket TTS - Vera voice)
- Works offline once cached
- Automatic fallback to browser TTS if WAV file is missing

### 4. Verify Cache is Working

Open browser console (F12) and look for:
```
[AudioCache] Loaded audio mapping: 30 entries
[AudioCache] Stats: {
  mappingLoaded: true,
  totalMappings: 30,
  cachedAudios: 0,
  mappingFile: "english-1-audio-mapping.json"
}
```

When playing audio, you'll see:
```
[AudioCache] Playing cached audio for: Good morning. How are you...
```

## 📁 Files Created

```
websocket-server/
├── public/assets/
│   ├── english-1.json                      # Original conversation
│   ├── english-1-audio-mapping.json        # Text → WAV filename mapping
│   └── wav/                                # Cached audio files
│       ├── good_morning_how_are_you_today_and_are_you_r_177337999.wav
│       ├── good_morning_i_am_doing_well_thank_you_and_ye_183391116.wav
│       └── ... (30 total WAV files)
```

## 🔄 Adding More Conversations

### Step 1: Create a new conversation JSON file
```bash
# Example: public/assets/english-2.json
```

### Step 2: Fetch audio for the new conversation
```bash
node cache-audio.js english-2.json
```

### Step 3: Open the player with the new file
```
http://localhost:3000/roleplay-player.html?file=english-2.json
```

## 🛠️ Useful Commands

### Fetch audio for a conversation
```bash
node cache-audio.js english-1.json
```

### Test TTS API with a single request
```bash
node test-tts-single.js
```

### Check cached files
```bash
ls -lh public/assets/wav/
```

### View mapping file
```bash
cat public/assets/english-1-audio-mapping.json | jq
```

### Clear cache and re-download
```bash
rm -rf public/assets/wav/*.wav
rm public/assets/*-audio-mapping.json
node cache-audio.js english-1.json
```

## 🎮 Gameplay Features

### Audio Playback Priority
1. **Cached WAV** - Plays first if available
2. **Browser TTS** - Automatic fallback if WAV fails or missing

### Replay Button
- Click the replay button on any dialogue card
- Uses cached audio when available
- Works for both current and past turns

### Performance Benefits
- **Instant playback** - No synthesis delay
- **Consistent quality** - Same voice every time
- **Offline capable** - Works without internet
- **Reduced CPU** - No real-time TTS processing

## 📊 Cache Statistics

### Storage Usage
- **Average WAV file:** ~200-300 KB per dialogue
- **30-line conversation:** ~6-8 MB total
- **Mapping file:** ~2-3 KB

### Current Cache
```bash
# Check total size
du -sh public/assets/wav/

# Count files
ls -1 public/assets/wav/*.wav | wc -l
```

## 🐛 Troubleshooting

### Audio not playing?
1. Check browser console for errors
2. Verify mapping file exists: `public/assets/english-1-audio-mapping.json`
3. Verify WAV files exist: `ls public/assets/wav/`
4. Check web server is serving static files correctly

### Want to disable cache and use TTS only?
Temporarily rename the mapping file:
```bash
mv public/assets/english-1-audio-mapping.json public/assets/english-1-audio-mapping.json.bak
```

### Re-enable cache:
```bash
mv public/assets/english-1-audio-mapping.json.bak public/assets/english-1-audio-mapping.json
```

## 🎯 Next Steps

1. **Test the player** - Open it and verify cached audio plays
2. **Create more conversations** - Add new JSON files and fetch their audio
3. **Customize voices** - Edit `VOICE` in `fetch-tts-audio.js` to try different voices
4. **Adjust delays** - Modify `DELAY_BETWEEN_REQUESTS` if needed

## 📚 Documentation

- Full documentation: `README-AUDIO-CACHE.md`
- Original player docs: `README.md`

## ✨ Features Summary

✅ Automatic audio caching from TTS API  
✅ Intelligent fallback to browser TTS  
✅ Offline playback support  
✅ Idempotent fetching (won't re-download)  
✅ Rate limiting protection  
✅ Progress tracking during fetch  
✅ Error handling and retry logic  

---

**Enjoy your enhanced roleplay conversation trainer!** 🎉
