const fs = require('fs');
const path = require('path');

function convertRomajiRawToSRT(inputFilePath, outputFilePath) {
    const rawContent = fs.readFileSync(inputFilePath, 'utf8');
    
    const regex = /(\d+)\s+([\d\s:,\n]+--\s*>\s*[\d\s:,\n]+\d)\s*([^\d].+?)(?=\s*\d+\s+[\d\s:,]+--\s*>|$)/gs;
    
    let srtContent = '';
    let match;
    let count = 0;
    
    while ((match = regex.exec(rawContent)) !== null) {
        const number = match[1].trim();
        let timecode = match[2].trim();
        let text = match[3].trim();
        
        timecode = timecode.replace(/[\s\n]+/g, '');
        timecode = timecode.replace('-->', ' --> ');
        
        text = text.replace(/\d+$/, '').trim();
        
        srtContent += `${number}\n`;
        srtContent += `${timecode}\n`;
        srtContent += `${text}\n\n`;
        
        count++;
    }
    
    console.log(`Converted ${count} entries`);
    fs.writeFileSync(outputFilePath, srtContent.trim() + '\n', 'utf8');
    console.log(`✓ Converted: ${path.basename(inputFilePath)}`);
    console.log(`  → Output: ${path.basename(outputFilePath)}`);
}

function processRomajiRawFiles() {
    const resultDir = path.join(__dirname, 'result-transcripts');
    
    if (!fs.existsSync(resultDir)) {
        console.error(`Error: result-transcripts directory not found: ${resultDir}`);
        process.exit(1);
    }
    
    const files = fs.readdirSync(resultDir);
    const romajiRawFiles = files.filter(file => file.endsWith('.srt.romajiraw'));
    
    if (romajiRawFiles.length === 0) {
        console.log('No .srt.romajiraw files found in result-transcripts directory.');
        return;
    }
    
    console.log(`Found ${romajiRawFiles.length} romaji raw file(s) to process:\n`);
    
    let successCount = 0;
    let errorCount = 0;
    
    romajiRawFiles.forEach((file, index) => {
        const inputPath = path.join(resultDir, file);
        const outputFileName = file.replace(/\.romajiraw$/, '.romaji');
        const outputPath = path.join(resultDir, outputFileName);
        
        console.log(`[${index + 1}/${romajiRawFiles.length}] Processing: ${file}`);
        
        try {
            convertRomajiRawToSRT(inputPath, outputPath);
            successCount++;
        } catch (error) {
            console.error(`✗ Error processing ${file}: ${error.message}\n`);
            errorCount++;
        }
    });
    
    console.log('='.repeat(50));
    console.log(`Conversion complete!`);
    console.log(`✓ Success: ${successCount} file(s)`);
    if (errorCount > 0) {
        console.log(`✗ Failed: ${errorCount} file(s)`);
    }
}

const args = process.argv.slice(2);

if (args.length === 0) {
    processRomajiRawFiles();
} else if (args.length === 1) {
    const inputFile = args[0];
    const outputFile = inputFile.replace(/\.romajiraw$/, '.romaji');
    
    try {
        convertRomajiRawToSRT(inputFile, outputFile);
    } catch (error) {
        console.error('Error converting romaji raw to SRT:', error.message);
        process.exit(1);
    }
} else {
    console.error('Usage:');
    console.error('  node convert-romaji-raw.js                          # Process all .srt.romajiraw files in result-transcripts/');
    console.error('  node convert-romaji-raw.js <input-file.romajiraw>   # Process single file');
    process.exit(1);
}
