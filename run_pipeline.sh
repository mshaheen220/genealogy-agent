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

echo -e "\n[2/4] Generating Profiles..."
python generate_profiles.py "../$FILTERED_GED"

echo -e "\n[3/4] Building SQLite Database..."
python build_sqlite.py "../$FILTERED_GED"
deactivate
cd ..

echo -e "\n[4/4] Building Vector Database..."
cd server-node
node build_index.js -i "../$PROFILES_DIR"
cd ..

echo -e "\n✅ Pipeline finished successfully! You can now start the server."