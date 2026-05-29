import argparse
import sqlite3
import re
from pathlib import Path

# Reuse the robust extraction logic we already built!
from generate_profiles import collect_relationships, get_name, get_event_date, extract_year

def main():
    parser = argparse.ArgumentParser(description="Build SQLite database from GEDCOM")
    parser.add_argument("gedcom_path", help="Path to the filtered GEDCOM file.")
    args = parser.parse_args()

    gedcom_path = Path(args.gedcom_path)
    match = re.search(r"family_tree_filtered_([A-Za-z0-9@_]+)\.ged", gedcom_path.name)
    root_id = match.group(1) if match else "default"
    db_path = gedcom_path.parent / f"genealogy_{root_id}.db"

    print(f"Reading GEDCOM data from {gedcom_path}...")
    rels = collect_relationships(gedcom_path)
    individuals = rels["individuals"]
    families = rels["families"]
    individual_to_fams = rels["individual_to_fams"]
    individual_to_famc = rels["individual_to_famc"]
    family_to_husb = rels["family_to_husb"]
    family_to_wife = rels["family_to_wife"]
    family_to_children = rels["family_to_children"]

    print(f"Creating SQLite database at {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS individuals")
    cursor.execute("""
        CREATE TABLE individuals (
            id TEXT PRIMARY KEY,
            full_name TEXT,
            first_name TEXT,
            last_name TEXT,
            gender TEXT,
            birth_date TEXT,
            birth_year INTEGER,
            death_date TEXT,
            death_year INTEGER,
            child_count INTEGER,
            spouse_count INTEGER,
            sibling_count INTEGER
        )
    """)

    cursor.execute("DROP TABLE IF EXISTS families")
    cursor.execute("""
        CREATE TABLE families (
            family_id TEXT PRIMARY KEY,
            husband_id TEXT,
            husband_name TEXT,
            wife_id TEXT,
            wife_name TEXT,
            marriage_date TEXT,
            marriage_year INTEGER,
            divorce_date TEXT,
            divorce_year INTEGER,
            child_count INTEGER
        )
    """)

    rows = []
    for xref_id, record in individuals.items():
        full_name = get_name(record)
        
        # Simple first/last name split for DB logic
        name_parts = full_name.split()
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[-1] if len(name_parts) > 1 else ""
        
        # Use ged4py's extracted surname if available for higher accuracy
        try:
            surname = ""
            if hasattr(record, "name") and record.name:
                surname = getattr(record.name, "surname", "")
                if not surname and hasattr(record.name, "value") and isinstance(record.name.value, tuple) and len(record.name.value) > 1:
                    surname = record.name.value[1]
            if not surname and hasattr(record, "sub_tag_value"):
                nv = record.sub_tag_value("NAME")
                if isinstance(nv, tuple) and len(nv) > 1:
                    surname = nv[1]
            if surname:
                last_name = str(surname).replace("/", "").strip()
        except Exception:
            pass

        gender = str(record.sub_tag_value("SEX")).strip().upper() if record.sub_tag_value("SEX") else ""
        birth_date = get_event_date(record.sub_tag("BIRT"))
        birth_year = extract_year(birth_date) if birth_date else None
        death_date = get_event_date(record.sub_tag("DEAT"))
        death_year = extract_year(death_date) if death_date else None
        spouse_count = len(individual_to_fams.get(xref_id, []))
        
        child_count = sum(len(family_to_children.get(fam_id, [])) for fam_id in individual_to_fams.get(xref_id, []))
        
        seen_siblings = set()
        sibling_count = sum(1 for fam_id in individual_to_famc.get(xref_id, []) for child_id in family_to_children.get(fam_id, []) if child_id != xref_id and child_id not in seen_siblings and not seen_siblings.add(child_id))

        rows.append((xref_id, full_name, first_name, last_name, gender, birth_date, birth_year, death_date, death_year, child_count, spouse_count, sibling_count))

    cursor.executemany("INSERT INTO individuals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)

    family_rows = []
    for fam_id, record in families.items():
        husb_id = family_to_husb.get(fam_id)
        wife_id = family_to_wife.get(fam_id)
        
        husb_name = get_name(individuals.get(husb_id)) if husb_id else ""
        wife_name = get_name(individuals.get(wife_id)) if wife_id else ""
        
        marr_record = record.sub_tag("MARR")
        marr_date = get_event_date(marr_record)
        marr_year = extract_year(marr_date) if marr_date else None
        
        div_record = record.sub_tag("DIV")
        div_date = get_event_date(div_record)
        div_year = extract_year(div_date) if div_date else None
        
        child_count = len(family_to_children.get(fam_id, []))
        
        family_rows.append((fam_id, husb_id, husb_name, wife_id, wife_name, marr_date, marr_year, div_date, div_year, child_count))

    cursor.executemany("INSERT INTO families VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", family_rows)
    conn.commit()
    conn.close()
    print(f"✅ Successfully inserted {len(rows)} individuals and {len(family_rows)} families into the database!")

if __name__ == "__main__":
    main()