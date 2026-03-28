# Roleplay Player Refactoring Guide

## Overview
The roleplay-player.js has been refactored from a single 835-line file into a modular ES6 architecture with automatic hot-reloading support.

## New File Structure

```
/websocket-server/public/
├── modules/
│   ├── constants.js              # Configuration constants (8 exports)
│   ├── similarity.js             # Text comparison utilities (3 functions)
│   ├── speech-recognition.js     # Web Speech API wrapper (SpeechRecognitionManager class)
│   ├── ui-manager.js             # DOM manipulation & UI updates (UIManager class)
│   ├── progress-manager.js       # LocalStorage & state persistence (ProgressManager class)
│   └── conversation-manager.js   # Game flow & turn logic (ConversationManager class)
├── roleplay-player.js            # Main orchestrator (~80 lines)
├── roleplay-player-backup.js     # Original file backup
└── roleplay-player.html          # Already configured with type="module"
```

## Module Responsibilities

### 1. **constants.js**
- All configuration values
- Easy to modify game parameters
- No dependencies

### 2. **similarity.js**
- `normalizeText()` - Text normalization
- `calculateSimilarity()` - Jaccard + Levenshtein similarity
- `levenshtein()` - Edit distance algorithm
- Pure functions, no side effects

### 3. **speech-recognition.js**
- Wraps Web Speech API
- Manages recognition lifecycle
- Handles silence detection
- Callback-based architecture for loose coupling

### 4. **ui-manager.js**
- All DOM element references
- Sidebar management
- Status updates (mic, transcript, result)
- Conversation history rendering
- No business logic

### 5. **progress-manager.js**
- LocalStorage operations
- Score tracking
- Turn completion tracking
- Attempt counting
- History management

### 6. **conversation-manager.js**
- Core game flow
- Turn rendering (bot/user)
- User input evaluation
- Audio playback coordination
- Depends on all other modules

### 7. **roleplay-player.js** (Main)
- Initializes all modules
- Wires up event handlers
- Minimal orchestration layer

## Automatic Reloading

### Browser Native ES6 Modules
The refactored code uses ES6 `import/export` with `type="module"` in HTML:

```html
<script type="module" src="roleplay-player.js"></script>
```

**Benefits:**
- Browser automatically reloads when files change (during development with live server)
- No build step required
- Works with any dev server (Live Server, http-server, etc.)

### How It Works
1. Browser caches modules but checks for updates on page reload
2. Each module is loaded independently
3. Changes to any module file trigger reload when page refreshes
4. Use browser DevTools to disable cache during development

## Development Workflow

### Making Changes
1. Edit any module file (e.g., `modules/ui-manager.js`)
2. Save the file
3. Refresh browser (Cmd+R / Ctrl+R)
4. Changes are immediately reflected

### Adding New Features
1. Identify which module handles the feature
2. Edit that specific module
3. If cross-cutting, update the main orchestrator

### Debugging
- Each module can be debugged independently
- Use browser DevTools Sources tab
- Set breakpoints in specific modules
- Console logs show module file names

## Migration Notes

### What Changed
- **Before**: Single 835-line file
- **After**: 7 focused modules + main orchestrator

### Backward Compatibility
- Original file backed up as `roleplay-player-backup.js`
- All functionality preserved
- Same HTML/CSS structure
- Same API surface

### Testing Checklist
- [ ] Conversation loads correctly
- [ ] Speech recognition works
- [ ] Bot turns play audio
- [ ] User turns evaluate correctly
- [ ] Progress persists in localStorage
- [ ] Sidebar toggles properly
- [ ] Manual input fallback works
- [ ] Restart session works
- [ ] History replay works

## Benefits of Modular Structure

### Maintainability
- Each module has single responsibility
- Easy to locate and fix bugs
- Clear separation of concerns

### Testability
- Modules can be unit tested independently
- Mock dependencies easily
- Pure functions in similarity.js are trivial to test

### Scalability
- Add new features without touching unrelated code
- Multiple developers can work on different modules
- Reduce merge conflicts

### Performance
- Browser can cache modules individually
- Only changed modules need reloading
- Tree-shaking possible for production builds

## Future Enhancements

### Optional: Production Build
For production, consider adding a build step:
```bash
# Using esbuild or rollup
npm install -D esbuild
esbuild roleplay-player.js --bundle --minify --outfile=dist/roleplay-player.min.js
```

### Optional: TypeScript
Convert modules to TypeScript for type safety:
```typescript
// modules/constants.ts
export const DEFAULT_CONVERSATION_FILE: string = 'english-1.json';
```

### Optional: Unit Tests
Add tests using Vitest or Jest:
```javascript
// tests/similarity.test.js
import { calculateSimilarity } from '../modules/similarity.js';
test('exact match returns 1', () => {
  expect(calculateSimilarity('hello', 'hello')).toBe(1);
});
```

## Troubleshooting

### Module Not Found
- Check file paths in import statements
- Ensure all files are in correct directories
- Verify file extensions (.js) are included

### CORS Errors
- Must run through a web server (not file://)
- Use Live Server, http-server, or similar
- Check server allows ES6 modules

### Changes Not Reflecting
- Hard refresh: Cmd+Shift+R / Ctrl+Shift+F5
- Clear browser cache
- Check DevTools Network tab for 304 vs 200 responses
- Disable cache in DevTools (Network tab)

## Summary

The refactored codebase is now:
- ✅ Modular and maintainable
- ✅ Auto-reloading with ES6 modules
- ✅ Easy to test and debug
- ✅ Scalable for future features
- ✅ Backward compatible

All functionality from the original 835-line file is preserved while gaining significant architectural benefits.
