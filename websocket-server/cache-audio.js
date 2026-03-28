#!/usr/bin/env node

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const SCRIPT_DIR = __dirname;
const WAV_DIR = path.join(SCRIPT_DIR, 'public', 'assets', 'wav');

function printHeader() {
    console.log('==========================================');
    console.log('Audio Cache Script');
    console.log('==========================================');
}

function printFooter(conversationFile) {
    console.log('');
    console.log('==========================================');
    console.log('Audio caching complete!');
    console.log('==========================================');
    console.log('');
    console.log('Next steps:');
    console.log('1. Start your web server if not already running');
    console.log(`2. Open: http://localhost:3000/roleplay-player.html?file=${conversationFile}`);
    console.log('3. Check browser console for cache statistics');
    console.log('');
}

function main() {
    const args = process.argv.slice(2);
    const conversationFile = args[0] || 'english-1.json';
    const conversationPath = path.join(SCRIPT_DIR, 'public', 'assets', conversationFile);

    printHeader();
    console.log(`Conversation file: ${conversationFile}`);
    console.log(`Output directory: ${WAV_DIR}`);
    console.log('');

    // Create wav directory if it doesn't exist
    if (!fs.existsSync(WAV_DIR)) {
        fs.mkdirSync(WAV_DIR, { recursive: true });
        console.log(`Created directory: ${WAV_DIR}`);
    }

    // Check if conversation file exists
    if (!fs.existsSync(conversationPath)) {
        console.error(`Error: Conversation file not found: ${conversationPath}`);
        process.exit(1);
    }

    // Run the fetch script
    console.log('Starting audio fetch process...');
    console.log('');

    try {
        const fetchScriptPath = path.join(SCRIPT_DIR, 'fetch-tts-audio.js');
        execSync(`node "${fetchScriptPath}" "${conversationFile}"`, {
            cwd: SCRIPT_DIR,
            stdio: 'inherit'
        });

        printFooter(conversationFile);
        process.exit(0);
    } catch (error) {
        console.error('');
        console.error('Error running fetch script:', error.message);
        process.exit(1);
    }
}

main();
