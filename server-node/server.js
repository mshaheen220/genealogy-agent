import "dotenv/config";
import express from "express";
import http from "http";
import { Server } from "socket.io";
import path from "path";
import { fileURLToPath } from "url";
import { pipeline } from "@xenova/transformers";
import * as lancedb from "@lancedb/lancedb";
import { ChatGoogleGenerativeAI } from "@langchain/google-genai";
import { SystemMessage, HumanMessage, AIMessage } from "@langchain/core/messages";
import { DatabaseSync } from "node:sqlite";

// TODO: allow for similar (same) names. e.g. How does it know which Michael Behun we mean?

// ES Module fix for __dirname
const __dirname = path.dirname(fileURLToPath(import.meta.url));

const app = express();
const server = http.createServer(app);
const io = new Server(server);

// Global AI Variables
let generateEmbedding, dbTable, llm, dbSql;

// Initialize AI Models & Database
async function initAI() {
  console.log("Loading AI model & connecting to Databases...");
  generateEmbedding = await pipeline("feature-extraction", "Xenova/all-MiniLM-L6-v2");
  const db = await lancedb.connect(path.resolve("../data/vector_store"));
  dbTable = await db.openTable("genealogy_profiles");
  dbSql = new DatabaseSync(path.resolve("../data/genealogy.db"));
  llm = new ChatGoogleGenerativeAI({
    model: "gemini-2.5-flash-lite",
    temperature: 0,
  });
  console.log("✅ AI & DB ready!");
}
initAI().catch(console.error);

app.use(express.static(path.join(__dirname, "public")));

io.on("connection", (socket) => {
  console.log("🟢 Client connected:", socket.id);

  // Give the agent short-term memory for this specific user session
  const chatHistory = [];

  socket.on("transcription", async (text) => {
    console.log(`\n🗣️  User said: "${text}"`);
    
    if (!dbTable || !generateEmbedding || !llm || !dbSql) {
      socket.emit("answer", "Still initializing AI... please wait a moment.");
      return;
    }

    try {
      const historyText = chatHistory.length > 0 
        ? chatHistory.map(m => `${m.role === 'user' ? 'User' : 'Agent'}: ${m.content}`).join('\n') 
        : "No previous history.";

      // 1. Intelligent Routing (SQL vs Vector)
      const routerResponse = await llm.invoke([
        new SystemMessage(`You are an intelligent routing assistant for a genealogy database.
Decide if the user's question requires a SQL query or a Vector Database search.

Use "sql" ONLY for global/aggregate math across the WHOLE family (e.g., "how many people total", "who had the most children", "who is the oldest").
Use "vector" for ANY question about a SPECIFIC PERSON (e.g., "how many children did Steven have", "when was Katherine born", stories, biographies). The vector database handles speech-to-text phonetic misspellings of names much better than SQL exact matches.

The SQLite database has two tables:
1. 'individuals': id TEXT, full_name TEXT, first_name TEXT, last_name TEXT, gender TEXT, birth_date TEXT, birth_year INTEGER, death_date TEXT, death_year INTEGER, child_count INTEGER, spouse_count INTEGER, sibling_count INTEGER
2. 'families': family_id TEXT, husband_id TEXT, husband_name TEXT, wife_id TEXT, wife_name TEXT, marriage_date TEXT, marriage_year INTEGER, divorce_date TEXT, divorce_year INTEGER, child_count INTEGER
If you must use SQL to search by name, ALWAYS use LIKE with wildcards (e.g., first_name LIKE '%Steven%') to account for misspellings.

RECENT CONVERSATION HISTORY:
${historyText}

IMPORTANT: If the user uses pronouns (he/she/that) or answers a clarification (e.g., "yes"), use the Conversation History to figure out exactly who or what they mean, and include the full name/topic in your vector search query or SQL query.

Respond ONLY with a valid JSON object. Do not include markdown formatting.
{
  "type": "sql" | "vector",
  "query": "The exact SQL query to run, OR a clean string of just the specific names/keywords for the vector database (e.g., 'Michael Shaheen' instead of 'Michael Shaheen information')"
}`),
        new HumanMessage(text)
      ]);

      let route;
      try {
        const cleanJson = routerResponse.content.replace(/```json/g, '').replace(/```/g, '').trim();
        route = JSON.parse(cleanJson);
      } catch (e) {
        console.warn("Router failed to output JSON, falling back to Vector Search.");
        route = { type: "vector", query: text };
      }

      if (route.type === "sql") {
        console.log(`📊 Routing to SQL Database: ${route.query}`);
        try {
          const sqlResults = dbSql.prepare(route.query).all();
          const contextText = JSON.stringify(sqlResults, null, 2);
          
          const aiResponse = await llm.invoke([
            new SystemMessage(`You are a helpful genealogy assistant. The user asked a question, and we automatically ran a SQL query to find the answer.

SQL QUERY RUN:
${route.query}

SQL RESULTS:
${contextText}

Assume the SQL results correctly answer the user's question. Formulate a polite, conversational response using ONLY these results. If it's a list of names, list them out naturally. If it's a count, state the number.`),
            ...chatHistory.map(m => m.role === 'user' ? new HumanMessage(m.content) : new AIMessage(m.content)),
            new HumanMessage(text),
          ]);

          console.log(`💡 Answer: ${aiResponse.content}`);
          const uiAnswer = `${aiResponse.content}<div style="margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(0,0,0,0.05); font-size: 0.85em; color: var(--text-muted);">⚙️ <b>Ran SQL:</b> <code>${route.query}</code></div>`;
          socket.emit("answer", uiAnswer);
          
          chatHistory.push({ role: "user", content: text });
          chatHistory.push({ role: "assistant", content: aiResponse.content });
          if (chatHistory.length > 10) chatHistory.splice(0, chatHistory.length - 10);
        } catch (err) {
          console.error("SQL Execution Error:", err.message);
          socket.emit("answer", "I tried to query the database, but I encountered a SQL error.");
        }
        return; // End the request here so we don't also run the Vector Search!
      }

      console.log(`🔍 Routing to Vector Search: ${route.query}`);

      // 2. Embed user query (using optimized LLM query)
      const output = await generateEmbedding([route.query], { pooling: "mean", normalize: true });
      const queryVector = output.tolist()[0];

      // 2. Wide Vector Search (cast a wider net to find hidden names)
      const rawResults = await dbTable.search(queryVector).limit(150).toArray();
      
      if (rawResults.length === 0) {
         socket.emit("answer", "I couldn't find any relevant family tree data.");
         return;
      }

      // 3. Custom Hybrid Re-ranking (Keyword Boost)
      // Vector databases struggle with exact names. We artificially boost the relevance 
      // of chunks that contain the exact keywords (names) from the user's query.
      const stopWords = new Set(["how", "who", "what", "where", "when", "why", "did", "does", "is", "the", "and", "for", "with", "have", "has", "had", "was", "were", "are", "old", "many", "any", "all", "about", "information", "detail", "details"]);
      // Use the optimized router query, and explicitly strip possessive 's so names match properly!
      const queryWords = route.query.toLowerCase().replace(/'s\b/g, '').replace(/[^a-z0-9\s]/g, '').split(' ').filter(w => !stopWords.has(w) && w.length > 2);
      
      // LanceDB returns read-only proxies. Map them to new objects to calculate scores.
      let results = rawResults.map(r => {
        let keywordScore = 0;
        const chunkText = r.text.toLowerCase();
        const sourceName = r.source.toLowerCase();
        queryWords.forEach(w => {
          if (chunkText.includes(w)) keywordScore += 0.5; // Boost for text matches
          if (sourceName.includes(w)) keywordScore += 10.0; // MASSIVE boost to keep ALL chunks of the matched file together at the top!
        });
        
        return {
          text: r.text,
          source: r.source,
          _distance: r._distance,
          _hybridScore: r._distance - keywordScore
        };
      });

      // Sort by the new hybrid score and keep the top 30 to ensure we don't drop timeline chunks
      results.sort((a, b) => a._hybridScore - b._hybridScore);
      results = results.slice(0, 30);

      // Log the top 3 files retrieved so we can debug if the database found the right person!
      const topSources = results.slice(0, 3).map(r => r.source).join(", ");
      console.log(`🔍 Retrieved top sources: ${topSources}`);

      // 4. RAG with Gemini
      // Inject the filename into each chunk so the LLM always knows whose profile it is reading!
      const contextText = results.map(r => `[Source Profile: ${r.source}]\n${r.text}`).join("\n\n");
      const today = new Date().toDateString();
      const aiResponse = await llm.invoke([
        new SystemMessage(`You are a highly capable genealogy assistant. Answer the user's question using ONLY the provided FAMILY TREE DATA.

CRITICAL RULES FOR REASONING:
1. PHONETIC MATCHING: The user is using speech-to-text. Names are spelled phonetically (e.g., "Catherine behun" -> "Katherine Behun"). You MUST match names by how they SOUND.
2. MAIDEN NAMES: Women are stored by their MAIDEN names. "Catherine Behun" means you must find a husband named "Behun" whose wife is "Katherine [Maiden Name]".
3. SPOUSE CROSS-REFERENCING: If asked about a marriage, look at the "Spouses:" section of BOTH partners. The husband's profile often has the wedding location!
4. EXHAUSTIVE SEARCH: Read ALL provided chunks. The first chunk might be a decoy.
5. DATA CLEANUP IS MANDATORY: You are powering a genealogy cleanup app. If ANY relevant information is missing for a matched person (e.g., unknown birth, unknown spouse), you MUST output a <cleanup> tag at the VERY END suggesting what to research next.
6. LIVING PEOPLE EXCEPTION: If a person was born less than 110 years ago and has an "Unknown" death date, THEY ARE ALIVE. Their death info is NOT missing, it just hasn't happened yet! Do NOT mention death records in your <cleanup> tag.

OUTPUT FORMAT:
1. You MUST wrap your internal reasoning in <thinking> tags. 
Inside the <thinking> tags, actively identify phonetic name matches, resolve maiden names, and cross-reference the spouses.
2. Write your polite, conversational answer to the user.
3. If ANY relevant data is missing or conflicting, add a <cleanup> tag at the VERY END with a brief, 1-sentence suggestion on what the user should research next. DO NOT suggest finding death records for people who are alive!

If the answer is completely missing after reasoning, say EXACTLY: "I don't know based on the family tree data."

FAMILY TREE DATA:\n${contextText}`),
        ...chatHistory.map(m => m.role === 'user' ? new HumanMessage(m.content) : new AIMessage(m.content)),
        new HumanMessage(text),
      ]);

      console.log(`💡 Raw AI Output:\n${aiResponse.content}`);
      
      // Remove thinking block first so we don't accidentally extract <cleanup> tags from the AI's internal monologue!
      let cleanContent = aiResponse.content.replace(/<thinking>[\s\S]*?<\/thinking>\n*/gi, '');
      
      const cleanupMatch = cleanContent.match(/<cleanup>([\s\S]*?)<\/cleanup>/i);
      const cleanupText = cleanupMatch ? cleanupMatch[1].trim() : null;
      
      cleanContent = cleanContent.replace(/<cleanup>[\s\S]*?<\/cleanup>\n*/gi, '').trim();
      
      // Convert Markdown bold to HTML bold so it renders beautifully in the Web UI
      const formattedContent = cleanContent.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>');
      let uiAnswer = `${formattedContent}`;
      
      if (cleanupText) {
        uiAnswer += `<div style="margin-top: 16px; padding: 12px 16px; background-color: #fffbeb; border-left: 4px solid #f59e0b; border-radius: 4px; font-size: 0.9em; color: #b45309; line-height: 1.5;">🧹 <b>Cleanup Suggestion:</b> ${cleanupText}</div>`;
      }
      uiAnswer += `<div style="margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(0,0,0,0.05); font-size: 0.85em; color: var(--text-muted);">📚 <b>Sources:</b> ${topSources.replace(/\.md/g, '').replace(/_/g, ' ')}</div>`;
      
      socket.emit("answer", uiAnswer);
      
      chatHistory.push({ role: "user", content: text });
      chatHistory.push({ role: "assistant", content: cleanContent });
      if (chatHistory.length > 10) chatHistory.splice(0, chatHistory.length - 10);
    } catch (err) {
      console.error("Error during RAG pipeline:", err);
      socket.emit("answer", "Sorry, an error occurred while searching the family tree.");
    }
  });

  socket.on("disconnect", () => {
    console.log("🔴 Client disconnected:", socket.id);
  });
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
  console.log(`🚀 Server listening on http://localhost:${PORT}`);
});