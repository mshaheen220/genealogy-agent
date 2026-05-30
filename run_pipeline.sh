#!/bin/bash
# Exit immediately if any command fails
set -e

if [ "$#" -ne 2 ]; then
    echo "Usage: ./run_pipeline.sh <path/to/original.ged> <ROOT_ID>"
    echo "Example: ./run_pipeline.sh data/source_trees/tree.ged I412076094635"
    exit 1
fi

GEDCOM_FILE="$1"
ROOT_ID="$2"

# Calculate the source dir, then define the new target directory structure
SOURCE_DIR=$(dirname "$GEDCOM_FILE")
FILTERED_SOURCE="$SOURCE_DIR/family_tree_filtered_${ROOT_ID}.ged"

TARGET_DIR="data/$ROOT_ID"
FILTERED_GED="$TARGET_DIR/family_tree_filtered.ged"
PROFILES_DIR="$TARGET_DIR/profiles"
RAW_MEDIA_DIR="$TARGET_DIR/raw_media"
DOCS_DIR="$TARGET_DIR/docs"
DB_PATH="$TARGET_DIR/genealogy.db"
VECTOR_DIR="$TARGET_DIR/vector_store"

echo "==========================================="
echo "🧬 Genealogy Agent - Full Pipeline Run"
echo "==========================================="

echo -e "\n[1/4] Filtering Tree..."
cd pipeline-python
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Creating it now..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi
python filter_tree.py --input "../$GEDCOM_FILE" --root-id "$ROOT_ID"

# Move the generated filtered tree into its dedicated ID directory
mkdir -p "../$TARGET_DIR"
if [ -f "../$FILTERED_SOURCE" ]; then
    mv "../$FILTERED_SOURCE" "../$FILTERED_GED"
fi

echo -e "\n[2/5] Generating Profiles..."
python generate_profiles.py "../$FILTERED_GED"

echo -e "\n[3/5] Building SQLite Database..."
python build_sqlite.py "../$FILTERED_GED"

echo -e "\n[4/5] (Optional) Processing Media..."
if [ -d "../$RAW_MEDIA_DIR" ]; then
    echo "Found $RAW_MEDIA_DIR directory, running OCR..."
    python process_media.py --root-id "$ROOT_ID"
fi
deactivate
cd ..

echo -e "\n[5/5] Building Vector Database..."
cd server-node
node build_index.js --root-id "$ROOT_ID"
cd ..

echo -e "\n✅ Pipeline finished successfully! You can now start the server."