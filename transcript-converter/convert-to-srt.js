const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

function parseTimestamp(timeStr) {
    const parts = timeStr.split(':');
    let hours = 0;
    let minutes = 0;
    let seconds = 0;

    if (parts.length === 3) {
        hours = parseInt(parts[0]);
        minutes = parseInt(parts[1]);
        seconds = parseInt(parts[2]);
    } else if (parts.length === 2) {
        minutes = parseInt(parts[0]);
        seconds = parseInt(parts[1]);
    }

    return hours * 3600 + minutes * 60 + seconds;
}

function formatSRTTime(seconds) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    const milliseconds = Math.floor((seconds % 1) * 1000);

    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')},${String(milliseconds).padStart(3, '0')}`;
}

function convertHTMLToSRT(htmlFilePath, outputFilePath) {
    const htmlContent = fs.readFileSync(htmlFilePath, 'utf8');
    
    const dom = new JSDOM(htmlContent);
    const document = dom.window.document;
    
    const segments = document.querySelectorAll('ytd-transcript-segment-renderer');
    
    const transcriptData = [];
    
    segments.forEach((segment) => {
        const timestampElement = segment.querySelector('.segment-timestamp');
        const textElement = segment.querySelector('.segment-text');
        
        if (timestampElement && textElement) {
            const timestamp = timestampElement.textContent.trim();
            const text = textElement.textContent.trim();
            
            transcriptData.push({
                timestamp: timestamp,
                text: text,
                seconds: parseTimestamp(timestamp)
            });
        }
    });
    
    let srtContent = '';
    
    for (let i = 0; i < transcriptData.length; i++) {
        const current = transcriptData[i];
        const next = transcriptData[i + 1];
        
        const startTime = current.seconds;
        const endTime = next ? next.seconds : current.seconds + 3;
        
        srtContent += `${i + 1}\n`;
        srtContent += `${formatSRTTime(startTime)} --> ${formatSRTTime(endTime)}\n`;
        srtContent += `${current.text}\n\n`;
    }
    
    fs.writeFileSync(outputFilePath, srtContent, 'utf8');
    console.log(`✓ SRT file created: ${outputFilePath}`);
    console.log(`✓ Total segments: ${transcriptData.length}`);
}

function processAllTranscripts() {
    const inputDir = path.join(__dirname, 'raw-transcripts');
    const outputDir = path.join(__dirname, 'result-transcripts');
    
    if (!fs.existsSync(inputDir)) {
        console.error(`Error: Input directory not found: ${inputDir}`);
        process.exit(1);
    }
    
    if (!fs.existsSync(outputDir)) {
        fs.mkdirSync(outputDir, { recursive: true });
        console.log(`✓ Created output directory: ${outputDir}`);
    }
    
    const files = fs.readdirSync(inputDir);
    const htmlFiles = files.filter(file => file.toLowerCase().endsWith('.html'));
    
    if (htmlFiles.length === 0) {
        console.log('No HTML files found in raw-transcripts directory.');
        return;
    }
    
    console.log(`Found ${htmlFiles.length} HTML file(s) to process:\n`);
    
    let successCount = 0;
    let errorCount = 0;
    
    htmlFiles.forEach((file, index) => {
        const inputPath = path.join(inputDir, file);
        const outputFileName = file.replace(/\.html$/i, '.srt');
        const outputPath = path.join(outputDir, outputFileName);
        
        console.log(`[${index + 1}/${htmlFiles.length}] Processing: ${file}`);
        
        try {
            convertHTMLToSRT(inputPath, outputPath);
            successCount++;
        } catch (error) {
            console.error(`✗ Error processing ${file}: ${error.message}`);
            errorCount++;
        }
        
        console.log('');
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
    processAllTranscripts();
} else if (args.length === 1) {
    const inputFile = args[0];
    const outputDir = path.join(__dirname, 'result-transcripts');
    
    if (!fs.existsSync(outputDir)) {
        fs.mkdirSync(outputDir, { recursive: true });
        console.log(`✓ Created output directory: ${outputDir}\n`);
    }
    
    const fileName = path.basename(inputFile);
    const outputFileName = fileName.replace(/\.html$/i, '.srt');
    const outputFile = path.join(outputDir, outputFileName);
    
    try {
        convertHTMLToSRT(inputFile, outputFile);
    } catch (error) {
        console.error('Error converting HTML to SRT:', error.message);
        process.exit(1);
    }
} else {
    console.error('Usage:');
    console.error('  node convert-to-srt.js                              # Process all files in raw-transcripts/');
    console.error('  node convert-to-srt.js <input-file.html>            # Process single file to result-transcripts/');
    process.exit(1);
}
