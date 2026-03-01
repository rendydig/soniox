You can replace your Gemini‑based `ChatGoogleGenerativeAI` model with an **xAI Grok API client** in Node‑js and keep the same `correctSentence` logic flow. Here’s a minimal, production‑ready version that uses Grok via the OpenAI‑compatible endpoint:

```js
require('dotenv').config({ path: '../.env' });

const { OpenAI } = require('openai'); // reusable OpenAI client

const client = new OpenAI({
  apiKey: process.env.GROK_API_KEY,
  baseURL: 'https://api.x.ai/v1', // xAI Grok endpoint
});

const MODEL = process.env.GROK_MODEL || 'grok-beta'; // or grok-1, grok-2, etc.
const TEMPERATURE = parseFloat(process.env.GROK_TEMPERATURE) || 0.3;

async function correctSentence(sentence) {
  try {
    const prompt = `You are a Multiple-Language grammar checker. Analyze the following sentence and determine if it needs correction.

Sentence: "${sentence}"

Rules:
1. If the sentence is grammatically correct and natural, respond with: {"status": "good", "original": "${sentence}"}
2. If the sentence has grammar errors or can be improved, respond with: {"status": "bad", "original": "${sentence}", "corrected": "[corrected version]"}

Respond ONLY with valid JSON, no additional text.`;

    const response = await client.chat.completions.create({
      model: MODEL,
      messages: [{ role: 'user', content: prompt }],
      temperature: TEMPERATURE,
    });

    const content = response.choices[0]?.message?.content?.trim();
    if (!content) {
      throw new Error('Empty response from Grok');
    }

    // Try to extract JSON object
    let jsonMatch = content.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      throw new Error('No JSON found in response');
    }

    const result = JSON.parse(jsonMatch[0]);

    return {
      status: result.status,
      original: result.original,
      corrected: result.corrected || null,
    };
  } catch (error) {
    console.error('[Grok Correction] Error:', error);
    return {
      status: 'error',
      original: sentence,
      corrected: null,
      error: error.message,
    };
  }
}

module.exports = { correctSentence };
```

### What you need to do

1. **Install dependencies** (if not already there):
   ```bash
   npm install openai dotenv
   ```

2. **Set in `.env`**:
   ```env
   GROK_API_KEY=sk-xxxx...
   GROK_MODEL=grok-2-small
   GROK_TEMPERATURE=0.3
   ```

3. **Use the same function signature** as before, so your existing call‑site stays unchanged:
   ```js
   const { correctSentence } = require('./corrector');

   const res = await correctSentence("This sentences is wrong.");
   console.log(res);
   // { status: 'bad', original: 'This sentences is wrong.', corrected: 'This sentence is wrong.' }
   ```

This approach:
- keeps your **JSON‑only contract** intact,
- swaps Gemini for Grok using the OpenAI‑compatible client,
- leaves you free to tune the model and temperature via `.env`. [aionlinecourse](https://www.aionlinecourse.com/blog/how-to-use-xai-grok-api-a-simple-guide-to-setup-and-integration)