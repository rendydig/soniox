const { correctSentence } = require('./gemini-correction');

const testSentences = [
  "てください。",
  "私は日本の京都出身です。",
  "皆さんはどこご出身ですか？",
  "よかったらコメント欄で教えてください。",
  "私は今も京都に住んでいます。",
  "皆さん。"
];

async function runTests() {
  console.log('🧪 Testing Grok Grammar Correction\n');
  console.log('='.repeat(60));
  
  for (let i = 0; i < testSentences.length; i++) {
    const sentence = testSentences[i];
    console.log(`\n[Test ${i + 1}/${testSentences.length}]`);
    console.log(`Original: "${sentence}"`);
    
    try {
      const result = await correctSentence(sentence);
      
      if (result.status === 'error') {
        console.log(`❌ Error: ${result.error}`);
      } else if (result.status === 'good') {
        console.log(`✅ Status: Good (no correction needed)`);
      } else if (result.status === 'bad') {
        console.log(`⚠️  Status: Needs correction`);
        console.log(`Corrected: "${result.corrected}"`);
      }
      
      console.log(`Response:`, JSON.stringify(result, null, 2));
    } catch (error) {
      console.log(`❌ Exception: ${error.message}`);
    }
    
    console.log('-'.repeat(60));
  }
  
  console.log('\n✨ Test completed!\n');
}

runTests().catch(console.error);
