#!/bin/bash

echo "🧹 Sweeping away generated data files..."

for dir in data/*/; do
    if [[ "$dir" == *"source_trees/"* ]]; then
        continue
    fi

    rm -rf "${dir}profiles"
    rm -rf "${dir}docs"
    rm -rf "${dir}vector_store"
    rm -f "${dir}family_tree_filtered.ged"
    rm -f "${dir}genealogy.db"
    rm -f "${dir}raw_media/.processed_log.txt"
done

# Remove legacy folders from earlier builds
rm -rf data/profiles data/vector_store data/genealogy.db
rm -rf data/family_tree_filtered_*.ged
rm -rf data/profiles_* data/docs_* data/genealogy_*.db data/vector_store_*
rm -rf data/raw_media_*/.processed_log.txt

echo "✨ All clean! You are ready for a fresh pipeline run."