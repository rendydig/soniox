const fs = require('fs');
const path = require('path');
const https = require('https');

const WAV_DIR = path.join(__dirname, 'public', 'assets', 'wav');
const TTS_API_URL = 'https://kyutaipockettts6ylex2y4-kyutai-pocket-tts.functions.fnc.fr-par.scw.cloud/tts';
const VOICE = 'vera';
const TEST_TEXT = 'Hello, this is a test.';

// Ensure wav directory exists
if (!fs.existsSync(WAV_DIR)) {
    fs.mkdirSync(WAV_DIR, { recursive: true });
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
        console.log('Testing URL:', TTS_API_URL);
        console.log('Hostname:', url.hostname);
        console.log('Path:', url.pathname);
        
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
        
        console.log('\nSending request...');
        
        const req = https.request(options, (res) => {
            console.log('Status Code:', res.statusCode);
            console.log('Headers:', res.headers);
            
            const chunks = [];
            
            res.on('data', (chunk) => {
                chunks.push(chunk);
            });
            
            res.on('end', () => {
                if (res.statusCode === 200) {
                    const buffer = Buffer.concat(chunks);
                    console.log('Received audio data:', buffer.length, 'bytes');
                    resolve(buffer);
                } else {
                    const responseText = Buffer.concat(chunks).toString();
                    console.log('Response body:', responseText);
                    reject(new Error(`HTTP ${res.statusCode}: ${res.statusMessage}`));
                }
            });
        });
        
        req.on('error', (error) => {
            console.error('Request error:', error);
            reject(error);
        });
        
        req.write(body);
        req.end();
    });
}

// Test the API
console.log('='.repeat(60));
console.log('TTS API Test - Single Request');
console.log('='.repeat(60));
console.log('Text:', TEST_TEXT);
console.log('Voice:', VOICE);
console.log('');

fetchAudio(TEST_TEXT, VOICE)
    .then((audioBuffer) => {
        const filename = 'test_audio.wav';
        const filepath = path.join(WAV_DIR, filename);
        fs.writeFileSync(filepath, audioBuffer);
        console.log('\n✓ Success!');
        console.log('Saved to:', filepath);
        console.log('File size:', audioBuffer.length, 'bytes');
    })
    .catch((error) => {
        console.error('\n✗ Failed:', error.message);
        console.error('Full error:', error);
        process.exit(1);
    });
