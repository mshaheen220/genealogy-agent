import argparse
import json
import os
import re
import sqlite3
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables from .env file
# Check common locations, including the server-node directory where the JS app stores it
env_paths = [
    Path(__file__).parent.parent / 'server-node' / '.env',
    Path(__file__).parent.parent / '.env',
    Path(__file__).parent / '.env'
]
for p in env_paths:
    if p.exists():
        load_dotenv(dotenv_path=p)
        break

# --- Gemini API Configuration ---
# Ensure your GOOGLE_API_KEY is set in your .env file
API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    raise ValueError("GOOGLE_API_KEY not found in environment variables. Please add it to your .env file.")
genai.configure(api_key=API_KEY)

# --- Triage & OCR Prompt ---
TRIAGE_PROMPT = """
You are a strict genealogical archivist evaluating a historical document. Read the attached image and decide if it contains genealogically significant information.

CRITERIA FOR RELEVANCE:
- **Relevant:** Obituaries, birth/death announcements, marriage/engagement notices, census ledgers, immigration records, military drafts, or major historical life events.
- **Not Relevant:** Minor school awards (spelling bees, honor roll), children's sports scores, generic social column mentions (e.g., 'The Smiths hosted a dinner party'), or advertisements.

After evaluating, perform these tasks:
1. Transcribe the full text of the document. **IMPORTANT: You MUST exclude any boilerplate text from the source website like 'Newspapers.com', 'Freeview', 'Try 7 Days Free', copyright notices, or trademark disclaimers. Focus only on the content of the historical clipping itself.**
2. Identify the primary people mentioned by their full names.
3. Identify the primary date of the document (e.g., "15 Oct 2002").
4. Identify the primary location mentioned (e.g., "Rocky River, Cuyahoga, Ohio, USA").

Output a single, valid JSON object with the following fields. Do not include markdown formatting.
{
  "is_relevant": true | false,
  "reason": "A 1-sentence explanation of why you kept or rejected it.",
  "transcription": "The full text of the document.",
  "people": ["Full Name 1", "Full Name 2"],
  "date": "The primary date found.",
  "location": "The primary location found."
}
"""

def make_safe_filename(base_name: str) -> str:
    """Creates a filesystem-safe filename."""
    base_name = re.sub(r"[^A-Za-z0-9_\- ]", "", base_name)
    return base_name.replace(" ", "_")

def find_person_ids(names: list[str], cursor: sqlite3.Cursor) -> dict[str, str | None]:
    """Queries the SQLite DB to find GEDCOM IDs for a list of names."""
    resolved_ids = {}
    for name in names:
        # Use LIKE to handle middle names or initials
        cursor.execute("SELECT id FROM individuals WHERE full_name LIKE ?", (f"%{name}%",))
        result = cursor.fetchone()
        resolved_ids[name] = result[0] if result else None
    return resolved_ids

def get_known_facts(resolved_ids: dict[str, str | None], cursor: sqlite3.Cursor) -> str:
    """Retrieves known vital facts for resolved individuals."""
    facts = []
    for name, pid in resolved_ids.items():
        if pid:
            cursor.execute("SELECT full_name, birth_date, death_date FROM individuals WHERE id = ?", (pid,))
            row = cursor.fetchone()
            if row:
                facts.append(f"- {row[0]}: Born {row[1] or 'Unknown'}, Died {row[2] or 'Unknown'}")
    return "\n".join(facts)

def process_media_file(file_path: Path, db_path: Path, output_dir: Path) -> bool:
    """Processes a single media file using Gemini for OCR and triage."""
    print(f"\nProcessing: {file_path.name}")
    
    # Upload the file to Gemini's servers (This natively supports images AND multi-page PDFs!)
    try:
        uploaded_file = genai.upload_file(path=str(file_path))
    except Exception as e:
        print(f"  - ❌ Error: Could not upload file to Gemini. {e}")
        return False

    model = genai.GenerativeModel('gemini-2.5-flash-lite')
    try:
        response = model.generate_content([TRIAGE_PROMPT, uploaded_file], stream=False)
        
        # Clean up the response from markdown code block
        clean_response = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_response)
    except Exception as e:
        print(f"  - ❌ Error: Failed to get valid response from Gemini API. {e}")
        return False
    finally:
        # Clean up the file from Google's servers after we get the response
        try:
            genai.delete_file(uploaded_file.name)
        except Exception:
            pass

    # --- Post-process transcription to remove boilerplate ---
    transcription = data.get('transcription')
    if transcription:
        # Define patterns for common boilerplate text to remove
        boilerplate_patterns = [
            r"(?s)The names, logos, and other source identifying features.*?archived at our site\.",
            r"(?s)\d{4}\s+Newspapers\.com.*?All Rights Reserved[.\s]*",
            r"Show article text \(OCR\)",
            r"Twitter\s+Facebook\s+Instagram\s+Blog",
            r"Note: This clipping was created at a time when the web was not as fast as it is today and has been replaced with a better quality image\.",
            r"Freeview Enjoy this clipping for free",
            r"Try 7 Days Free(?: to get access to [\d,]+ million\+ pages(?: Try 7 Days Free)?)?",
            r"Newspapers\.com",
        ]
        for pattern in boilerplate_patterns:
            transcription = re.sub(pattern, "", transcription, flags=re.IGNORECASE).strip()
        
        # Remove excessive newlines that might result from substitution
        transcription = re.sub(r'(\n\s*){3,}', '\n\n', transcription).strip()
        data['transcription'] = transcription

    print(f"  - Triage Reason: {data.get('reason', 'N/A')}")

    if not data.get('is_relevant'):
        print("  - 🟡 Skipping: Document deemed not genealogically relevant.")
        return True

    # --- Entity Resolution ---
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    tagged_people_ids = find_person_ids(data.get('people', []), cursor)
    known_facts = get_known_facts(tagged_people_ids, cursor)
    conn.close()

    tagged_people_str = ", ".join([f"{name} ({id})" if id else name for name, id in tagged_people_ids.items()])
    all_unlinked = all(pid is None for pid in tagged_people_ids.values()) if tagged_people_ids else True
    any_unlinked = any(pid is None for pid in tagged_people_ids.values()) if tagged_people_ids else True
    
    if all_unlinked:
        status_line = "- **Status:** ⚠️ UNLINKED ORPHAN"
    elif any_unlinked:
        status_line = "- **Status:** ⚠️ PARTIALLY LINKED (Some people not in tree)"
    else:
        status_line = "- **Status:** Linked"

    # --- Conflict Auditor (2nd Pass) ---
    conflicts_text = ""
    if known_facts and data.get('transcription'):
        conflict_prompt = f"""
        You are a genealogical auditor. Compare this document transcription against known database facts.
        
        TRANSCRIPTION:
        {data.get('transcription', '')}
        
        KNOWN FACTS:
        {known_facts}
        
        Does the transcription explicitly contradict any of the known facts (e.g. different birth year)?
        Output a JSON object:
        {{
          "has_conflict": true | false,
          "conflict_details": "1 sentence explaining the conflict, or null."
        }}
        """
        try:
            conflict_resp = model.generate_content(conflict_prompt)
            clean_conflict = conflict_resp.text.replace("```json", "").replace("```", "").strip()
            c_data = json.loads(clean_conflict)
            if c_data.get("has_conflict") and c_data.get("conflict_details"):
                conflicts_text = f"\n\n## ⚠️ Data Conflicts\n{c_data['conflict_details']}"
        except Exception as e:
            print(f"  - ⚠️ Warning: Conflict audit failed. {e}")

    # --- Markdown Generation ---
    doc_date = data.get('date') or 'Unknown Date'
    people_names = data.get('people') or ['Unknown_Person']
    
    # Use only the first person to keep filenames manageable
    primary_person = make_safe_filename(people_names[0])
    if len(people_names) > 1:
        primary_person += "_et_al"
        
    # Truncate the date string just in case the AI hallucinated a long sentence
    safe_date = make_safe_filename(doc_date)[:20].strip("_")
    
    filename_base = f"DOC_{primary_person}_{safe_date}"
    output_filename = f"{filename_base}.md"
    
    counter = 1
    while (output_dir / output_filename).exists():
        output_filename = f"{filename_base}_{counter}.md"
        counter += 1

    markdown_content = f"""# Document: {file_path.name}

{status_line}
- **Tagged People:** {tagged_people_str or "None"}
- **Document Date:** {doc_date}
- **Document Location:** {data.get('location') or 'Unknown'}
{conflicts_text}

## Transcription

{data.get('transcription', 'No transcription available.')}
"""
    
    output_path = output_dir / output_filename
    output_path.write_text(markdown_content.strip(), encoding="utf-8")
    print(f"  - ✅ Success: Saved relevant document to {output_path.name}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Process media files for genealogy using AI.")
    parser.add_argument("--data-dir", required=True, help="Base directory containing the data folders.")
    parser.add_argument("--root-id", required=True, help="The root ID for the current lineage.")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    root_id = args.root_id
    
    input_dir = data_dir / root_id / "raw_media"
    output_dir = data_dir / root_id / "docs"
    db_path = data_dir / root_id / "genealogy.db"

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")
    
    output_dir.mkdir(exist_ok=True)

    processed_log_path = input_dir / ".processed_log.txt"
    processed_files = set()
    if processed_log_path.exists():
        with open(processed_log_path, "r") as f:
            processed_files = set(line.strip() for line in f)

    files_to_process = [
        f for f in input_dir.iterdir() 
        if f.is_file() and f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.pdf'] and f.name not in processed_files
    ]

    if not files_to_process:
        print("No new media files to process.")
        return

    print(f"Found {len(files_to_process)} new media files to process.")

    for file_path in files_to_process:
        if process_media_file(file_path, db_path, output_dir):
            with open(processed_log_path, "a") as f:
                f.write(f"{file_path.name}\n")

    print("\nMedia processing complete.")


if __name__ == "__main__":
    main()