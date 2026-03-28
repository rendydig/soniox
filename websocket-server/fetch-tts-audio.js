const fs = require('fs');
const path = require('path');
const https = require('https');

const ASSETS_DIR = path.join(__dirname, 'public', 'assets');
const TTS_API_URL = 'https://kyutaipockettts6ylex2y4-kyutai-pocket-tts.functions.fnc.fr-par.scw.cloud/tts';
const VOICE = 'eve';
const DELAY_BETWEEN_REQUESTS = 1000; // 1 second delay between requests

/**
 * Generate a safe filename from text
 */
function generateFilename(text) {
    const hash = text
        .toLowerCase()
        .replace(/[^a-z0-9\s]/g, '')
        .replace(/\s+/g, '_')
        .substring(0, 50);
    
    // Create a simple hash for uniqueness
    let simpleHash = 0;
    for (let i = 0; i < text.length; i++) {
        simpleHash = ((simpleHash << 5) - simpleHash) + text.charCodeAt(i);
        simpleHash = simpleHash & simpleHash;
    }
    
    return `${hash}_${Math.abs(simpleHash)}.wav`;
}

/**
 * Create multipart form data body
 */
function createMultipartBody(text, voice) {
    const boundary = '----WebKitFormBoundary' + Math.random().toString(36).substring(2);
    
    let body = '';
    body += `--${boundary}\r\n`;
    body += `Content-Disposition: form-data; name="text"\r\n\r\n`;
    body += `${text}\r\n`;
    body += `--${boundary}\r\n`;
    body += `Content-Disposition: form-data; name="voice_url"\r\n\r\n`;
    body += `${voice}\r\n`;
    body += `--${boundary}--\r\n`;
    
    return { body, boundary };
}

/**
 * Fetch audio from TTS API
 */
function fetchAudio(text, voice) {
    return new Promise((resolve, reject) => {
        const { body, boundary } = createMultipartBody(text, voice);
        
        const url = new URL(TTS_API_URL);
        const options = {
            hostname: url.hostname,
            path: url.pathname,
            method: 'POST',
            headers: {
                'accept': '*/*',
                'accept-language': 'en-ID,en;q=0.9,id-ID;q=0.8,id;q=0.7,en-GB;q=0.6,en-US;q=0.5',
                'content-type': `multipart/form-data; boundary=${boundary}`,
                'content-length': Buffer.byteLength(body),
                'sec-ch-ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"macOS"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'cross-site',
                'referer': 'https://kyutai.org/'
            }
        };
        
        const req = https.request(options, (res) => {
            const chunks = [];
            
            res.on('data', (chunk) => {
                chunks.push(chunk);
            });
            
            res.on('end', () => {
                if (res.statusCode === 200) {
                    const buffer = Buffer.concat(chunks);
                    resolve(buffer);
                } else {
                    reject(new Error(`HTTP ${res.statusCode}: ${res.statusMessage}`));
                }
            });
        });
        
        req.on('error', (error) => {
            reject(error);
        });
        
        req.write(body);
        req.end();
    });
}

/**
 * Process a single dialogue entry
 */
async function processDialogue(dialogue, index, total, wavDir) {
    const text = dialogue.english;
    const filename = generateFilename(text);
    const filepath = path.join(wavDir, filename);
    
    // Check if file already exists
    if (fs.existsSync(filepath)) {
        console.log(`[${index + 1}/${total}] ✓ Already cached: ${filename}`);
        return { success: true, cached: true, filename };
    }
    
    try {
        console.log(`[${index + 1}/${total}] Fetching: "${text.substring(0, 60)}..."`);
        const audioBuffer = await fetchAudio(text, VOICE);
        
        fs.writeFileSync(filepath, audioBuffer);
        console.log(`[${index + 1}/${total}] ✓ Saved: ${filename} (${audioBuffer.length} bytes)`);
        
        return { success: true, cached: false, filename };
    } catch (error) {
        console.error(`[${index + 1}/${total}] ✗ Failed: ${error.message}`);
        return { success: false, cached: false, filename: null, error: error.message };
    }
}

/**
 * Main function to process all dialogues from a JSON file
 */
async function processConversationFile(jsonFilename) {
    const jsonPath = path.join(ASSETS_DIR, jsonFilename);
    
    if (!fs.existsSync(jsonPath)) {
        console.error(`Error: File not found: ${jsonPath}`);
        process.exit(1);
    }
    
    // Create WAV directory based on JSON filename
    const jsonBaseName = path.basename(jsonFilename, '.json');
    const WAV_DIR = path.join(ASSETS_DIR, 'wav', jsonBaseName);
    
    // Ensure wav directory exists
    if (!fs.existsSync(WAV_DIR)) {
        fs.mkdirSync(WAV_DIR, { recursive: true });
        console.log(`Created directory: ${WAV_DIR}`);
    }
    
    console.log(`\nLoading conversation file: ${jsonFilename}`);
    const conversationData = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
    const dialogues = conversationData.dialogue || [];
    
    console.log(`Found ${dialogues.length} dialogue entries`);
    console.log(`Output directory: ${WAV_DIR}\n`);
    
    const results = {
        total: dialogues.length,
        success: 0,
        failed: 0,
        cached: 0,
        errors: []
    };
    
    // Create a mapping file for quick lookup
    const mapping = {};
    
    for (let i = 0; i < dialogues.length; i++) {
        const dialogue = dialogues[i];
        const result = await processDialogue(dialogue, i, dialogues.length, WAV_DIR);
        
        if (result.success) {
            results.success++;
            if (result.cached) {
                results.cached++;
            }
            
            // Add to mapping
            mapping[dialogue.english] = result.filename;
        } else {
            results.failed++;
            results.errors.push({
                turn: dialogue.turn,
                text: dialogue.english,
                error: result.error
            });
        }
        
        // Delay between requests to avoid rate limiting
        if (i < dialogues.length - 1 && !result.cached) {
            await new Promise(resolve => setTimeout(resolve, DELAY_BETWEEN_REQUESTS));
        }
    }
    
    // Save mapping file
    const mappingFilename = jsonFilename.replace('.json', '-audio-mapping.json');
    const mappingPath = path.join(ASSETS_DIR, mappingFilename);
    fs.writeFileSync(mappingPath, JSON.stringify(mapping, null, 2));
    
    console.log('\n' + '='.repeat(60));
    console.log('SUMMARY');
    console.log('='.repeat(60));
    console.log(`Total dialogues: ${results.total}`);
    console.log(`Successfully processed: ${results.success}`);
    console.log(`Already cached: ${results.cached}`);
    console.log(`Failed: ${results.failed}`);
    console.log(`Mapping saved to: ${mappingFilename}`);
    
    if (results.errors.length > 0) {
        console.log('\nErrors:');
        results.errors.forEach(err => {
            console.log(`  Turn ${err.turn}: ${err.error}`);
        });
    }
    
    console.log('='.repeat(60) + '\n');
}

// Main execution
const args = process.argv.slice(2);
const jsonFilename = args[0] || 'english-1.json';

processConversationFile(jsonFilename)
    .then(() => {
        console.log('✓ Processing complete!');
        process.exit(0);
    })
    .catch((error) => {
        console.error('Fatal error:', error);
        process.exit(1);
    });
