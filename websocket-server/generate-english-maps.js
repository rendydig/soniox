const fs = require('fs');
const path = require('path');

const ASSETS_DIR = path.join(__dirname, 'public', 'assets');
const OUTPUT_FILE = path.join(ASSETS_DIR, 'maps-english.json');

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

        for (const file of englishFiles) {
            const filePath = path.join(ASSETS_DIR, file);
            const content = fs.readFileSync(filePath, 'utf8');
            const data = JSON.parse(content);

            maps.push({
                file: file,
                title: data.title || 'Untitled',
                estimated_duration_minutes: data.estimated_duration_minutes || 0,
                theme: data.theme || '',
                language: data.language || { source: 'English', translation: 'Indonesian' },
                participants: data.participants || []
            });
        }

        const output = {
            generated_at: new Date().toISOString(),
            total_games: maps.length,
            games: maps
        };

        fs.writeFileSync(OUTPUT_FILE, JSON.stringify(output, null, 2), 'utf8');
        
        console.log(`✓ Generated maps-english.json with ${maps.length} games`);
        console.log(`✓ Output: ${OUTPUT_FILE}`);
        
        maps.forEach((game, index) => {
            console.log(`  ${index + 1}. ${game.file} - ${game.title}`);
        });

    } catch (error) {
        console.error('Error generating maps:', error);
        process.exit(1);
    }
}

generateEnglishMaps();
