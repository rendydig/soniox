const { ChatGoogleGenerativeAI } = require("@langchain/google-genai");
require('dotenv').config({ path: '../.env' });

const model = new ChatGoogleGenerativeAI({
  apiKey: process.env.GEMINI_API_KEY,
  model: process.env.GEMINI_MODEL || "gemini-2.5-flash",
  temperature: 0.3,
});

async function correctSentence(sentence) {
  try {
    const prompt = `You are an Multiple-Language grammar checker. Analyze the following sentence and determine if it needs correction.

Sentence: "${sentence}"

Rules:
1. If the sentence is grammatically correct and natural, respond with: {"status": "good", "original": "${sentence}"}
2. If the sentence has grammar errors or can be improved, respond with: {"status": "bad", "original": "${sentence}", "corrected": "[corrected version]"}

Respond ONLY with valid JSON, no additional text.`;

    const response = await model.invoke(prompt);
    const content = response.content.trim();
    
    let jsonMatch = content.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      throw new Error('No JSON found in response');
    }
    
    const result = JSON.parse(jsonMatch[0]);
    
    return {
      status: result.status,
      original: result.original,
      corrected: result.corrected || null
    };
  } catch (error) {
    console.error('[Gemini Correction] Error:', error);
    return {
      status: 'error',
      original: sentence,
      corrected: null,
      error: error.message
    };
  }
}

module.exports = { correctSentence };
