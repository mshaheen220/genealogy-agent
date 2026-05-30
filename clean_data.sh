#!/bin/bash

echo "🧹 Sweeping away generated data files..."

rm -rf data/family_tree_filtered_*.ged
rm -rf data/profiles_*
rm -rf data/docs_*
rm -rf data/genealogy_*.db
rm -rf data/vector_store_*
rm -f data/raw_media_*/.processed_log.txt

# Remove legacy folders from earlier builds
rm -rf data/profiles data/vector_store data/genealogy.db

echo "✨ All clean! You are ready for a fresh pipeline run."