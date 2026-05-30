import "dotenv/config";
import { RecursiveCharacterTextSplitter } from "@langchain/textsplitters";
import { pipeline } from "@xenova/transformers";
import * as lancedb from "@lancedb/lancedb";
import * as arrow from "apache-arrow";
import { Command } from "commander";
import path from "path";
import fs from "fs";

// 1. Parse command-line arguments dynamically
const program = new Command();
program
  .requiredOption("-d, --data-dir <path>", "Base directory containing the data folders")
  .requiredOption("-r, --root-id <id>", "The root ID for the current lineage")
  .parse(process.argv);

const options = program.opts();

async function run() {
  const dataDir = path.resolve(options.dataDir);
  const rootId = options.rootId;

  const inputDirs = [
    path.join(dataDir, rootId, "profiles"),
    path.join(dataDir, rootId, "docs")
  ];
  const outputDir = path.join(dataDir, rootId, "vector_store");

  const splitter = new RecursiveCharacterTextSplitter({
    chunkSize: 1000,
    chunkOverlap: 200,
  });

  const chunkedDocs = [];
  
  for (const inputDir of inputDirs) {
    if (!fs.existsSync(inputDir)) {
      console.log(`⚠️  Directory does not exist (skipping): ${inputDir}`);
      continue;
    }

    console.log(`Loading Markdown files from: ${inputDir}`);
    const files = fs.readdirSync(inputDir).filter(f => f.endsWith(".md"));
    console.log(`Loaded ${files.length} documents from ${path.basename(inputDir)}.`);

    for (const file of files) {
      const filePath = path.join(inputDir, file);
      const text = fs.readFileSync(filePath, "utf-8");
      if (text.trim().length === 0) continue; // Skip empty files
      const chunks = await splitter.createDocuments([text], [{ source: file }]);
      
      // Filter out any empty chunks that might break vector inference
      chunkedDocs.push(...chunks.filter(c => c.pageContent.trim().length > 0));
    }
  }

  if (chunkedDocs.length === 0) {
    console.error("Error: No valid markdown chunks found across provided directories.");
    process.exit(1);
  }

  console.log(`Split profiles into ${chunkedDocs.length} valid vectorized chunks.`);

  // 4. Initialize Local Embeddings (No API Key Required!)
  // This will securely process your family data locally without cloud safety filters.
  console.log("Downloading/Loading local AI model (this will take a few seconds the first time)...");
  const generateEmbedding = await pipeline("feature-extraction", "Xenova/all-MiniLM-L6-v2");

  // 5. Connect to local LanceDB and ingest the documents
  console.log(`Connecting to local LanceDB at: ${outputDir}`);
  const db = await lancedb.connect(outputDir);
  
  console.log("Generating embeddings and saving to LanceDB...");

  const texts = chunkedDocs.map((doc) => doc.pageContent);
  const validDocs = [];
  const validVectors = [];
  let expectedDimension = 0;

  // Google's API can return empty arrays for chunks that trip safety filters.
  // Additionally, the batchEmbedContents API is known to silently fail an entire batch 
  // if even one chunk is flagged. We bypass this by using embedQuery in parallel batches.
  const BATCH_SIZE = 15;
  for (let i = 0; i < texts.length; i += BATCH_SIZE) {
    const batch = texts.slice(i, i + BATCH_SIZE);
    const batchDocs = chunkedDocs.slice(i, i + BATCH_SIZE);
    console.log(`Embedding batch ${Math.floor(i / BATCH_SIZE) + 1} of ${Math.ceil(texts.length / BATCH_SIZE)}...`);
    
    let batchVectors = [];
    try {
      const output = await generateEmbedding(batch, { pooling: "mean", normalize: true });
      batchVectors = output.tolist();
    } catch (err) {
      console.warn(`⚠️ Error embedding batch: ${err.message}`);
      continue;
    }

    for (let j = 0; j < batchVectors.length; j++) {
      const vec = batchVectors[j];
      if (expectedDimension === 0) expectedDimension = vec.length;
      validDocs.push(batchDocs[j]);
      validVectors.push(vec);
    }
  }

  if (validVectors.length === 0) {
    throw new Error("No valid embeddings were generated. Cannot create vector database.");
  }

  console.log(`Successfully embedded ${validVectors.length} out of ${texts.length} chunks.`);

  // Use standard JS Arrays and explicitly define an Apache Arrow Schema
  // to completely bypass LanceDB's native schema inference bugs.
  const data = validDocs.map((doc, i) => ({
    vector: Array.from(validVectors[i]),
    text: doc.pageContent,
    source: doc.metadata.source || "unknown",
    metadata: JSON.stringify(doc.metadata)
  }));

  const schema = new arrow.Schema([
    new arrow.Field("vector", new arrow.FixedSizeList(expectedDimension, new arrow.Field("item", new arrow.Float32(), true)), false),
    new arrow.Field("text", new arrow.Utf8(), true),
    new arrow.Field("source", new arrow.Utf8(), true),
    new arrow.Field("metadata", new arrow.Utf8(), true)
  ]);

  await db.createTable("genealogy_profiles", data, { mode: "overwrite", schema });

  console.log(`\n✅ Success! Local Vector Database stored at: ${outputDir}`);
}

run().catch((err) => {
  console.error("An error occurred during ingestion:", err);
  process.exit(1);
});