# Game Selector System

This system allows users to browse and select different English conversation games in the roleplay player.

## Overview

The game selector automatically generates a map of all available English game files and provides a UI for users to browse and switch between games.

## Files

- **`generate-english-maps.js`** - Node.js script that scans the `public/assets` folder for `english-*.json` files and generates a map file
- **`public/assets/maps-english.json`** - Generated map file containing metadata for all English games
- **`public/modules/game-selector.js`** - Frontend module that handles the game selection UI
- **Modal UI in `roleplay-player.html`** - Game selection modal interface
- **Styles in `roleplay-player.css`** - Styling for the game selector modal and cards

## Usage

### Generating the Maps File

Whenever you add a new `english-*.json` file to the `public/assets` folder, regenerate the maps file:

```bash
npm run generate-maps
```

Or directly:

```bash
node generate-english-maps.js
```

This will:
1. Scan for all files matching `english-{number}.json`
2. Extract metadata (title, duration, theme, participants)
3. Generate `public/assets/maps-english.json`

### Using the Game Selector

1. Open the roleplay player in your browser
2. Click the **art_track** icon button in the top-left corner
3. Browse the list of available games
4. Click on any game card to switch to that game
5. The page will reload with the selected game

### Game File Format

Each `english-*.json` file should have this structure:

```json
{
  "title": "Game Title",
  "estimated_duration_minutes": 15,
  "theme": "Brief description of the theme",
  "language": {
    "source": "English",
    "translation": "Indonesian"
  },
  "participants": ["Speaker1", "Speaker2"],
  "dialogue": [...]
}
```

### Maps File Format

The generated `maps-english.json` has this structure:

```json
{
  "generated_at": "2026-03-28T23:18:27.257Z",
  "total_games": 4,
  "games": [
    {
      "file": "english-1.json",
      "title": "Getting Started - Daily Business Conversation: Boss and You",
      "estimated_duration_minutes": 15,
      "theme": "General daily business conversation",
      "language": { "source": "English", "translation": "Indonesian" },
      "participants": ["Boss", "You"]
    }
  ]
}
```

## API Endpoint

The maps file is served via HTTP GET:

```
GET /assets/maps-english.json
```

## Features

- **Automatic scanning** - Finds all `english-{number}.json` files
- **Metadata extraction** - Pulls title, duration, theme, and participants
- **Sorted list** - Games are sorted numerically
- **Visual UI** - Clean modal interface with game cards
- **Active indicator** - Shows which game is currently loaded
- **Responsive design** - Works on desktop and mobile

## Adding New Games

1. Create a new file: `public/assets/english-{number}.json`
2. Follow the game file format above
3. Run `npm run generate-maps`
4. The new game will appear in the selector

## Development

The game selector is integrated into the main `RoleplayConversationPlayer` class and initializes automatically when the page loads.

Key components:
- `GameSelector` class handles modal interactions
- `loadGames()` fetches the maps file
- `renderGames()` creates the game cards
- `selectGame()` navigates to the selected game
