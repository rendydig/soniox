require('dotenv').config({ path: '../.env' });
const { OpenAI } = require('openai');
const { ChatGoogleGenerativeAI } = require("@langchain/google-genai");

const testSentences = [
  "てください。",
  "私は日本の京都出身です。",
  "皆さんはどこご出身ですか？",
  "よかったらコメント欄で教えてください。",
  "私は今も京都に住んでいます。",
  "皆さん。"
];

// Grok client
const grokClient = new OpenAI({
  apiKey: process.env.GROK_API_KEY,
  baseURL: 'https://api.x.ai/v1',
});

// Gemini client
const geminiModel = new ChatGoogleGenerativeAI({
  apiKey: process.env.GEMINI_API_KEY,
  model: process.env.GEMINI_MODEL || "gemini-2.5-flash-lite",
  temperature: 0.3,
});

async function correctWithGrok(sentence) {
  const prompt = `You are a Multiple-Language grammar checker. Analyze the following sentence and determine if it needs correction.

Sentence: "${sentence}"

Rules:
1. If the sentence is grammatically correct and natural, respond with: {"status": "good", "original": "${sentence}"}
2. If the sentence has grammar errors or can be improved, respond with: {"status": "bad", "original": "${sentence}", "corrected": "[corrected version]"}

Respond ONLY with valid JSON, no additional text.`;

  const response = await grokClient.chat.completions.create({
    model: process.env.GROK_MODEL || 'grok-4-1-fast',
    messages: [{ role: 'user', content: prompt }],
    temperature: 0.3,
  });

  const content = response.choices[0]?.message?.content?.trim();
  let jsonMatch = content.match(/\{[\s\S]*\}/);
  return JSON.parse(jsonMatch[0]);
}

async function correctWithGemini(sentence) {
  const prompt = `You are a Multiple-Language grammar checker. Analyze the following sentence and determine if it needs correction.

Sentence: "${sentence}"

Rules:
1. If the sentence is grammatically correct and natural, respond with: {"status": "good", "original": "${sentence}"}
2. If the sentence has grammar errors or can be improved, respond with: {"status": "bad", "original": "${sentence}", "corrected": "[corrected version]"}

Respond ONLY with valid JSON, no additional text.`;

  const response = await geminiModel.invoke(prompt);
  const content = response.content.trim();
  let jsonMatch = content.match(/\{[\s\S]*\}/);
  return JSON.parse(jsonMatch[0]);
}

async function testModel(name, correctionFn, sentences) {
  console.log(`\n🔬 Testing ${name}...`);
  const times = [];
  
  for (let i = 0; i < sentences.length; i++) {
    const sentence = sentences[i];
    const startTime = Date.now();
    
    try {
      await correctionFn(sentence);
      const duration = Date.now() - startTime;
      times.push(duration);
      console.log(`  [${i + 1}/${sentences.length}] ${duration}ms - "${sentence.substring(0, 30)}${sentence.length > 30 ? '...' : ''}"`);
    } catch (error) {
      console.log(`  [${i + 1}/${sentences.length}] ❌ Error: ${error.message}`);
    }
  }
  
  return times;
}

function calculateStats(times) {
  if (times.length === 0) return { avg: 0, min: 0, max: 0, total: 0 };
  
  const total = times.reduce((sum, t) => sum + t, 0);
  const avg = total / times.length;
  const min = Math.min(...times);
  const max = Math.max(...times);
  
  return { avg, min, max, total };
}

async function runComparison() {
  console.log('⚡ Speed Comparison: Grok vs Gemini');
  console.log('='.repeat(60));
  console.log(`Testing with ${testSentences.length} Japanese sentences\n`);
  
//   // Test Grok
//   const grokTimes = await testModel('Grok 4.1 Fast', correctWithGrok, testSentences);
//   const grokStats = calculateStats(grokTimes);
  
  // Test Gemini
  const geminiTimes = await testModel('Gemini 2.5 Flash', correctWithGemini, testSentences);
  const geminiStats = calculateStats(geminiTimes);
  
  // Results
  console.log('\n' + '='.repeat(60));
  console.log('📊 RESULTS');
  console.log('='.repeat(60));
  
//   console.log('\n🤖 Grok 4.1 Fast:');
//   console.log(`   Average: ${grokStats.avg.toFixed(2)}ms`);
//   console.log(`   Min: ${grokStats.min}ms`);
//   console.log(`   Max: ${grokStats.max}ms`);
//   console.log(`   Total: ${grokStats.total}ms`);
  
  console.log('\n✨ Gemini 2.5 Flash:');
  console.log(`   Average: ${geminiStats.avg.toFixed(2)}ms`);
  console.log(`   Min: ${geminiStats.min}ms`);
  console.log(`   Max: ${geminiStats.max}ms`);
  console.log(`   Total: ${geminiStats.total}ms`);
  
  // Comparison
  console.log('\n🏆 Winner:');
  if (grokStats.avg < geminiStats.avg) {
    const speedup = ((geminiStats.avg - grokStats.avg) / geminiStats.avg * 100).toFixed(1);
    console.log(`   Grok is ${speedup}% faster (${(geminiStats.avg - grokStats.avg).toFixed(2)}ms faster on average)`);
  } else {
    const speedup = ((grokStats.avg - geminiStats.avg) / grokStats.avg * 100).toFixed(1);
    console.log(`   Gemini is ${speedup}% faster (${(grokStats.avg - geminiStats.avg).toFixed(2)}ms faster on average)`);
  }
  
  console.log('\n' + '='.repeat(60));
}

runComparison().catch(console.error);
