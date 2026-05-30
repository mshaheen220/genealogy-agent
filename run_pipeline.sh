#!/bin/bash
# Exit immediately if any command fails
set -e

if [ "$#" -ne 2 ]; then
    echo "Usage: ./run_pipeline.sh <path/to/original.ged> <ROOT_ID>"
    echo "Example: ./run_pipeline.sh data/tree.ged I412076094635"
    exit 1
fi

GEDCOM_FILE="$1"
ROOT_ID="$2"

# Calculate the dynamically generated file and folder names
DATA_DIR=$(dirname "$GEDCOM_FILE")
FILTERED_GED="$DATA_DIR/family_tree_filtered_${ROOT_ID}.ged"
PROFILES_DIR="$DATA_DIR/profiles_${ROOT_ID}"
RAW_MEDIA_DIR="$DATA_DIR/raw_media_${ROOT_ID}"
DOCS_DIR="$DATA_DIR/docs_${ROOT_ID}"
DB_PATH="$DATA_DIR/genealogy_${ROOT_ID}.db"
VECTOR_DIR="$DATA_DIR/vector_store_${ROOT_ID}"

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

echo -e "\n[2/5] Generating Profiles..."
python generate_profiles.py "../$FILTERED_GED"

echo -e "\n[3/5] Building SQLite Database..."
python build_sqlite.py "../$FILTERED_GED"

echo -e "\n[4/5] (Optional) Processing Media..."
if [ -d "../$RAW_MEDIA_DIR" ]; then
    echo "Found $RAW_MEDIA_DIR directory, running OCR..."
    python process_media.py --data-dir "../$DATA_DIR" --root-id "$ROOT_ID"
fi
deactivate
cd ..

echo -e "\n[5/5] Building Vector Database..."
cd server-node
node build_index.js --data-dir "../$DATA_DIR" --root-id "$ROOT_ID"
cd ..

echo -e "\n✅ Pipeline finished successfully! You can now start the server."