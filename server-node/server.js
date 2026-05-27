import "dotenv/config";
import express from "express";
import http from "http";
import { Server } from "socket.io";
import path from "path";
import { fileURLToPath } from "url";
import { pipeline } from "@xenova/transformers";
import * as lancedb from "@lancedb/lancedb";
import { ChatGoogleGenerativeAI } from "@langchain/google-genai";
import { SystemMessage, HumanMessage } from "@langchain/core/messages";

// TODO: allow for similar (same) names. e.g. How does it know which Michael Behun we mean?

// ES Module fix for __dirname
const __dirname = path.dirname(fileURLToPath(import.meta.url));

const app = express();
const server = http.createServer(app);
const io = new Server(server);

// Global AI Variables
let generateEmbedding, dbTable, llm;

// Initialize AI Models & Database
async function initAI() {
  console.log("Loading AI model & connecting to Vector DB...");
  generateEmbedding = await pipeline("feature-extraction", "Xenova/all-MiniLM-L6-v2");
  const db = await lancedb.connect(path.resolve("../data/vector_store"));
  dbTable = await db.openTable("genealogy_profiles");
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

  socket.on("transcription", async (text) => {
    console.log(`\n🗣️  User said: "${text}"`);
    
    if (!dbTable || !generateEmbedding || !llm) {
      socket.emit("answer", "Still initializing AI... please wait a moment.");
      return;
    }

    try {
      // 1. Embed user query
      const output = await generateEmbedding([text], { pooling: "mean", normalize: true });
      const queryVector = output.tolist()[0];

      // 2. Wide Vector Search (cast a wider net to find hidden names)
      const rawResults = await dbTable.search(queryVector).limit(60).toArray();
      
      if (rawResults.length === 0) {
         socket.emit("answer", "I couldn't find any relevant family tree data.");
         return;
      }

      // 3. Custom Hybrid Re-ranking (Keyword Boost)
      // Vector databases struggle with exact names. We artificially boost the relevance 
      // of chunks that contain the exact keywords (names) from the user's query.
      const stopWords = new Set(["how", "who", "what", "where", "when", "why", "did", "does", "is", "the", "and", "for", "with", "have", "has", "had", "was", "were", "are", "old", "many", "any"]);
      const queryWords = text.toLowerCase().replace(/[^a-z0-9\s]/g, '').split(' ').filter(w => !stopWords.has(w) && w.length > 2);
      
      // LanceDB returns read-only proxies. Map them to new objects to calculate scores.
      let results = rawResults.map(r => {
        let keywordScore = 0;
        const chunkText = r.text.toLowerCase();
        queryWords.forEach(w => {
          if (chunkText.includes(w)) keywordScore += 0.25; // Massive boost for exact word matches
        });
        
        return {
          text: r.text,
          source: r.source,
          _distance: r._distance,
          _hybridScore: r._distance - keywordScore
        };
      });

      // Sort by the new hybrid score and keep the top 20
      results.sort((a, b) => a._hybridScore - b._hybridScore);
      results = results.slice(0, 20);

      // Log the top 3 files retrieved so we can debug if the database found the right person!
      console.log(`🔍 Retrieved top sources: ${results.slice(0, 3).map(r => r.source).join(", ")}`);

      // 4. RAG with Gemini
      const contextText = results.map(r => r.text).join("\n\n");
      const today = new Date().toDateString();
      const aiResponse = await llm.invoke([
        new SystemMessage(`You are a helpful genealogy assistant. Answer the user's question using ONLY the provided family tree context below. If the answer is not in the context, say "I don't know based on the family tree data."

IMPORTANT INSTRUCTIONS:
- Today's date is ${today}. Use this to calculate ages if asked.
- The user's question was transcribed from speech-to-text audio. Names may be misspelled phonetically. Use your best judgment.
- ALIASES & NICKNAMES: Pay close attention to the "Also known as" field in the context! People are frequently called by these alternative names.
- WOMEN'S NAMES: The family tree uses MAIDEN names. If the user asks about a married woman using her husband's last name (e.g., "Catherine Behan"), look for a woman with that first name whose spouse has that last name (e.g., "Katherine Sutyak" married to a "Behun"). You MUST use deductive reasoning to connect them!

CONTEXT:\n${contextText}`),
        new HumanMessage(text)
      ]);

      console.log(`💡 Answer: ${aiResponse.content}`);
      socket.emit("answer", aiResponse.content);
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