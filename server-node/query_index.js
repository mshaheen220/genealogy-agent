import "dotenv/config";
import { ChatGoogleGenerativeAI } from "@langchain/google-genai";
import { SystemMessage, HumanMessage } from "@langchain/core/messages";
import { pipeline } from "@xenova/transformers";
import * as lancedb from "@lancedb/lancedb";
import { Command } from "commander";
import path from "path";

// 1. Parse command-line arguments dynamically
const program = new Command();
program
  .requiredOption("-q, --query <text>", "The question or topic to search for in the family tree")
  .option("-d, --database <path>", "Relative path to the LanceDB vector store", "../data/vector_store")
  .option("-k, --limit <number>", "Number of results to return", "15")
  .parse(process.argv);

const options = program.opts();

async function run() {
  const dbPath = path.resolve(options.database);
  const queryText = options.query;
  const limit = parseInt(options.limit, 10);

  // 2. Load the local model to embed the user's search query
  // (This will be instant now since it's already downloaded!)
  const generateEmbedding = await pipeline("feature-extraction", "Xenova/all-MiniLM-L6-v2");
  const output = await generateEmbedding([queryText], { pooling: "mean", normalize: true });
  const queryVector = output.tolist()[0];

  // 3. Connect to the local vector database
  const db = await lancedb.connect(dbPath);
  const table = await db.openTable("genealogy_profiles");

  console.log(`\n🔍 Searching for: "${queryText}"\n`);

  // 4. Perform the semantic vector search
  const results = await table.search(queryVector).limit(limit).toArray();

  if (results.length === 0) {
    console.log("No results found.");
    return;
  }

  // 5. Print the results
  results.forEach((res, i) => {
    console.log(`--- Result ${i + 1} (Distance: ${res._distance.toFixed(4)}) ---`);
    console.log(`Source File: ${res.source}`);
    console.log(`Excerpt:\n${res.text.trim()}\n`);
  });

  // 6. Connect to an LLM to generate the final human-readable answer (RAG)
  console.log("\n🧠 Analyzing retrieved data and generating answer...");
  
  const contextText = results.map(r => r.text).join("\n\n");
  const llm = new ChatGoogleGenerativeAI({
    model: "gemini-2.5-flash-lite",
    temperature: 0,
  });

  const aiResponse = await llm.invoke([
    new SystemMessage(`You are a helpful genealogy assistant. Answer the user's question using ONLY the provided family tree context below. If the answer is not in the context, say "I don't know based on the family tree data."\n\nCONTEXT:\n${contextText}`),
    new HumanMessage(queryText)
  ]);

  console.log(`\n💡 Answer:\n${aiResponse.content}\n`);
}

run().catch(console.error);