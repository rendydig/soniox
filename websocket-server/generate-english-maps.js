const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const ASSETS_DIR = path.join(__dirname, 'public', 'assets');
const OUTPUT_FILE = path.join(ASSETS_DIR, 'maps-english.json');
const FETCH_TTS_SCRIPT = path.join(__dirname, 'fetch-tts-audio.js');

function checkAudioFiles(jsonFile) {
    const jsonBaseName = path.basename(jsonFile, '.json');
    const wavDir = path.join(ASSETS_DIR, 'wav', jsonBaseName);
    const jsonPath = path.join(ASSETS_DIR, jsonFile);
    
    if (!fs.existsSync(jsonPath)) {
        return { exists: false, hasAudio: false, totalDialogues: 0, audioFiles: 0 };
    }
    
    const data = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
    const dialogues = data.dialogue || [];
    
    if (!fs.existsSync(wavDir)) {
        return { exists: true, hasAudio: false, totalDialogues: dialogues.length, audioFiles: 0 };
    }
    
    const wavFiles = fs.readdirSync(wavDir).filter(f => f.endsWith('.wav'));
    
    return {
        exists: true,
        hasAudio: wavFiles.length > 0,
        totalDialogues: dialogues.length,
        audioFiles: wavFiles.length,
        isComplete: wavFiles.length >= dialogues.length
    };
}

function generateAudioForFile(jsonFile) {
    console.log(`\n🔊 Generating audio for ${jsonFile}...`);
    try {
        execSync(`node "${FETCH_TTS_SCRIPT}" "${jsonFile}"`, {
            stdio: 'inherit',
            cwd: __dirname
        });
        console.log(`✓ Audio generation completed for ${jsonFile}`);
        return true;
    } catch (error) {
        console.error(`✗ Failed to generate audio for ${jsonFile}:`, error.message);
        return false;
    }
}

function generateEnglishMaps() {
    try {
        const files = fs.readdirSync(ASSETS_DIR);
        
        const englishFiles = files.filter(file => {
            return /^english-\d+\.json$/.test(file);
        }).sort((a, b) => {
            const numA = parseInt(a.match(/\d+/)[0]);
            const numB = parseInt(b.match(/\d+/)[0]);
            return numA - numB;
        });

        const maps = [];
        const filesNeedingAudio = [];

        console.log('\n📋 Checking audio files for each English game...');
        console.log('='.repeat(60));

        for (const file of englishFiles) {
            const filePath = path.join(ASSETS_DIR, file);
            const content = fs.readFileSync(filePath, 'utf8');
            const data = JSON.parse(content);

            const audioCheck = checkAudioFiles(file);
            
            let audioStatus = '✗ No audio';
            if (audioCheck.hasAudio) {
                if (audioCheck.isComplete) {
                    audioStatus = `✓ Complete (${audioCheck.audioFiles}/${audioCheck.totalDialogues})`;
                } else {
                    audioStatus = `⚠ Incomplete (${audioCheck.audioFiles}/${audioCheck.totalDialogues})`;
                    filesNeedingAudio.push(file);
                }
            } else if (audioCheck.exists) {
                audioStatus = `✗ Missing (0/${audioCheck.totalDialogues})`;
                filesNeedingAudio.push(file);
            }
            
            console.log(`${file.padEnd(20)} - ${audioStatus}`);

            maps.push({
                file: file,
                title: data.title || 'Untitled',
                estimated_duration_minutes: data.estimated_duration_minutes || 0,
                image: data.image || '',
                theme: data.theme || '',
                language: data.language || { source: 'English', translation: 'Indonesian' },
                participants: data.participants || [],
                audio_status: audioCheck
            });
        }
        
        console.log('='.repeat(60));

        const output = {
            generated_at: new Date().toISOString(),
            total_games: maps.length,
            games: maps
        };

        fs.writeFileSync(OUTPUT_FILE, JSON.stringify(output, null, 2), 'utf8');
        
        console.log(`\n✓ Generated maps-english.json with ${maps.length} games`);
        console.log(`✓ Output: ${OUTPUT_FILE}`);
        
        if (filesNeedingAudio.length > 0) {
            console.log(`\n⚠ Found ${filesNeedingAudio.length} file(s) with missing or incomplete audio:`);
            filesNeedingAudio.forEach((file, index) => {
                console.log(`  ${index + 1}. ${file}`);
            });
            
            console.log(`\n🔧 Would you like to generate missing audio? (y/n)`);
            console.log(`   Run: node generate-english-maps.js --generate-audio`);
            
            if (process.argv.includes('--generate-audio')) {
                console.log(`\n🚀 Starting audio generation for ${filesNeedingAudio.length} file(s)...`);
                let successCount = 0;
                
                for (const file of filesNeedingAudio) {
                    if (generateAudioForFile(file)) {
                        successCount++;
                    }
                }
                
                console.log(`\n✓ Audio generation complete: ${successCount}/${filesNeedingAudio.length} successful`);
            }
        } else {
            console.log(`\n✓ All files have complete audio!`);
        }
        
        console.log(`\n📊 Game Summary:`);
        maps.forEach((game, index) => {
            const audioIcon = game.audio_status.isComplete ? '✓' : (game.audio_status.hasAudio ? '⚠' : '✗');
            console.log(`  ${index + 1}. ${audioIcon} ${game.file} - ${game.title}`);
        });

    } catch (error) {
        console.error('Error generating maps:', error);
        process.exit(1);
    }
}

generateEnglishMaps();
