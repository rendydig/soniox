const fs = require('fs');
const path = require('path');

function fixSrtTimestampFormat(content) {
    const timestampRegex = /(\d{2}:\d{2}:\d{2})\.(\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2})\.(\d{3})/g;
    
    return content.replace(timestampRegex, (match, startTime, startMs, endTime, endMs) => {
        return `${startTime},${startMs} --> ${endTime},${endMs}`;
    });
}

function fixSrtFile(inputPath, outputPath = null) {
    if (!fs.existsSync(inputPath)) {
        console.error(`Error: File not found: ${inputPath}`);
        return;
    }

    const content = fs.readFileSync(inputPath, 'utf8');
    const fixedContent = fixSrtTimestampFormat(content);
    
    const output = outputPath || inputPath;
    fs.writeFileSync(output, fixedContent, 'utf8');
    
    console.log(`✓ Fixed SRT format: ${output}`);
}

function fixSrtDirectory(dirPath) {
    if (!fs.existsSync(dirPath)) {
        console.error(`Error: Directory not found: ${dirPath}`);
        return;
    }

    const files = fs.readdirSync(dirPath);
    const srtFiles = files.filter(file => file.endsWith('.srt'));
    
    if (srtFiles.length === 0) {
        console.log('No .srt files found in directory');
        return;
    }

    console.log(`Found ${srtFiles.length} SRT file(s)`);
    
    srtFiles.forEach(file => {
        const filePath = path.join(dirPath, file);
        fixSrtFile(filePath);
    });
    
    console.log(`\n✓ Fixed ${srtFiles.length} file(s)`);
}

const args = process.argv.slice(2);

if (args.length === 0) {
    console.log('Usage:');
    console.log('  node fix-srt-format.js <file.srt>           - Fix single file');
    console.log('  node fix-srt-format.js <file.srt> <output>  - Fix and save to output');
    console.log('  node fix-srt-format.js <directory>          - Fix all .srt files in directory');
    process.exit(1);
}

const inputPath = args[0];
const outputPath = args[1];

const stats = fs.statSync(inputPath);

if (stats.isDirectory()) {
    fixSrtDirectory(inputPath);
} else if (stats.isFile()) {
    fixSrtFile(inputPath, outputPath);
} else {
    console.error('Error: Invalid input path');
    process.exit(1);
}
