from __future__ import annotations

import argparse
import html
import os
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ged4py import GedcomReader
IGNORE_INDI_TAGS = {"NAME", "SEX", "FAMC", "FAMS", "SOUR", "OBJE"}
EVENT_LABELS = {
    "BIRT": "Born",
    "DEAT": "Died",
    "BURI": "Buried",
    "CHR": "Christened",
    "BAPM": "Baptized",
    "MARR": "Married",
    "RESI": "Resided",
    "OCCU": "Occupation",
    "CENS": "Census",
}


@dataclass(frozen=True)
class IndividualProfile:
    xref_id: str
    name: str
    aliases: list[str]
    birth_date: str
    birth_place: str
    death_date: str
    death_place: str
    parents: list[str]
    spouses: list[str]
    children: list[str]
    timeline: list[str]
    notes: list[str]
    sources: list[str]


def normalize_text(value: Any) -> str:
    if value is None:
        return "Unknown"
    text = str(value).strip()
    return text or "Unknown"


def format_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def format_place(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def make_safe_filename(name: str, xref_id: str) -> str:
    base_name = name.replace("/", "").strip()
    if not base_name:
        base_name = xref_id.strip("@")
    base_name = re.sub(r"[^A-Za-z0-9_\- ]", "", base_name)
    base_name = base_name.replace(" ", "_")
    if not base_name:
        base_name = xref_id.strip("@")
    return f"{base_name}_{xref_id.strip('@')}.md"


def get_name(record: Any) -> str:
    if record is None:
        return "Unknown"
        
    def clean_gedcom_name(raw_name: str) -> str:
        # Replaces slashes with spaces and normalizes multiple spaces into one
        return " ".join(raw_name.replace("/", " ").split())

    def format_name_parts(given: str, surname: str) -> str:
        given_parts = given.split()
        suffixes = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}
        extracted_suffixes = []
        new_given = []
        for p in given_parts:
            if p.lower() in suffixes:
                extracted_suffixes.append(p)
            else:
                new_given.append(p)
        
        parts = new_given + [surname] + extracted_suffixes
        return " ".join(p for p in parts if p)

    # If the record itself is a Name object/tag
    given = getattr(record, "given", "") or ""
    surname = getattr(record, "surname", "") or ""
    if given or surname:
        return format_name_parts(given, surname)

    if hasattr(record, "name") and record.name:
        try:
            name_obj = record.name
            given = getattr(name_obj, "given", "") or ""
            surname = getattr(name_obj, "surname", "") or ""
            
            if given or surname:
                return format_name_parts(given, surname)
                
            if hasattr(name_obj, "value") and name_obj.value:
                if isinstance(name_obj.value, tuple):
                    g = name_obj.value[0] if len(name_obj.value) > 0 else ""
                    s = name_obj.value[1] if len(name_obj.value) > 1 else ""
                    return format_name_parts(g, s)
                return clean_gedcom_name(str(name_obj.value))
            return clean_gedcom_name(str(name_obj))
        except Exception:
            pass
            
    if hasattr(record, "sub_tag_value"):
        name_value = record.sub_tag_value("NAME")
        if name_value:
            if isinstance(name_value, tuple):
                g = name_value[0] if len(name_value) > 0 else ""
                s = name_value[1] if len(name_value) > 1 else ""
                return format_name_parts(g, s)
            return clean_gedcom_name(str(name_value))
            
    # Fallback if record is a tag with a value
    if hasattr(record, "value") and record.value:
        if isinstance(record.value, tuple):
            g = record.value[0] if len(record.value) > 0 else ""
            s = record.value[1] if len(record.value) > 1 else ""
            return format_name_parts(g, s)
        return clean_gedcom_name(str(record.value))

    if hasattr(record, "xref_id"):
        return record.xref_id
    return "Unknown"


def collect_relationships(path: Path) -> dict[str, Any]:
    families = {}
    individuals = {}
    sources: dict[str, Any] = {}
    individual_to_famc: dict[str, list[str]] = defaultdict(list)
    individual_to_fams: dict[str, list[str]] = defaultdict(list)
    family_to_husb: dict[str, str] = {}
    family_to_wife: dict[str, str] = {}
    family_to_children: dict[str, list[str]] = defaultdict(list)

    with GedcomReader(str(path)) as reader:
        for record in reader.records0():
            if record.tag == "INDI":
                individuals[record.xref_id] = record
                for sub in record.sub_records:
                    if sub.tag == "FAMC" and isinstance(sub.value, str):
                        individual_to_famc[record.xref_id].append(sub.value)
                    elif sub.tag == "FAMS" and isinstance(sub.value, str):
                        individual_to_fams[record.xref_id].append(sub.value)
            elif record.tag == "FAM":
                families[record.xref_id] = record
                for sub in record.sub_records:
                    if sub.tag == "HUSB" and isinstance(sub.value, str):
                        family_to_husb[record.xref_id] = sub.value
                    elif sub.tag == "WIFE" and isinstance(sub.value, str):
                        family_to_wife[record.xref_id] = sub.value
                    elif sub.tag == "CHIL" and isinstance(sub.value, str):
                        family_to_children[record.xref_id].append(sub.value)
            elif record.tag == "SOUR":
                sources[record.xref_id] = record

    return {
        "individuals": individuals,
        "families": families,
        "sources": sources,
        "individual_to_famc": individual_to_famc,
        "individual_to_fams": individual_to_fams,
        "family_to_husb": family_to_husb,
        "family_to_wife": family_to_wife,
        "family_to_children": family_to_children,
    }


def get_event_date(event_record: Any) -> str | None:
    if not event_record:
        return None
    date_value = event_record.sub_tag_value("DATE") if hasattr(event_record, "sub_tag_value") else None
    return format_date(date_value)


def get_event_place(event_record: Any) -> str | None:
    if not event_record:
        return None
    place_value = event_record.sub_tag_value("PLAC") if hasattr(event_record, "sub_tag_value") else None
    return format_place(place_value)


def normalize_optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def clean_text(value: Any) -> str | None:
    text = normalize_optional(value)
    if text is None:
        return None
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip() or None


def collect_record_notes_and_sources(record: Any) -> tuple[list[str], set[str]]:
    notes: list[str] = []
    source_ids: set[str] = set()

    def walk(item: Any) -> None:
        for sub in getattr(item, "sub_records", []):
            if sub.tag == "NOTE" and sub.value is not None:
                cleaned = clean_text(sub.value)
                if cleaned:
                    notes.append(cleaned)
            elif sub.tag == "SOUR" and isinstance(sub.value, str):
                source_ids.add(sub.value.strip())
            walk(sub)

    walk(record)
    return notes, source_ids


def describe_event(tag: str, date: str | None, place: str | None, detail: str | None = None) -> str | None:
    label = EVENT_LABELS.get(tag, tag.title())
    components = []
    if date:
        components.append(date)
    if place:
        components.append(place)
    if detail and detail.lower() != "unknown":
        components.append(detail)
    if components:
        return f"{label}: {' | '.join(components)}"
    return None


def summarize_source_record(source_record: Any) -> str:
    title = clean_text(source_record.sub_tag_value("TITL"))
    author = clean_text(source_record.sub_tag_value("AUTH"))
    publisher = clean_text(source_record.sub_tag_value("PUBL"))
    page = clean_text(source_record.sub_tag_value("PAGE"))
    note = clean_text(source_record.sub_tag_value("NOTE"))
    publ_record = source_record.sub_tag("PUBL")
    publ_date = get_event_date(publ_record)
    publ_place = get_event_place(publ_record)

    components = []
    if title:
        components.append(title)
    if author:
        components.append(f"Author: {author}")
    if publisher:
        components.append(f"Publisher: {publisher}")
    if publ_date:
        components.append(f"Date: {publ_date}")
    if publ_place:
        components.append(f"Place: {publ_place}")
    if page:
        components.append(f"Page: {page}")
    if note:
        components.append(f"Note: {note}")

    summary = "; ".join(components) if components else "Source record"
    return summary


def build_individual_profile(
    xref_id: str,
    individuals: dict[str, Any],
    families: dict[str, Any],
    sources: dict[str, Any],
    individual_to_famc: dict[str, list[str]],
    individual_to_fams: dict[str, list[str]],
    family_to_husb: dict[str, str],
    family_to_wife: dict[str, str],
    family_to_children: dict[str, list[str]],
) -> IndividualProfile:
    record = individuals[xref_id]
    name = get_name(record)

    surname = ""
    try:
        if hasattr(record, "name") and record.name:
            surname = getattr(record.name, "surname", "")
            if not surname and hasattr(record.name, "value") and isinstance(record.name.value, tuple) and len(record.name.value) > 1:
                surname = record.name.value[1]
        if not surname and hasattr(record, "sub_tag_value"):
            nv = record.sub_tag_value("NAME")
            if isinstance(nv, tuple) and len(nv) > 1:
                surname = nv[1]
    except Exception:
        pass
    surname = clean_text(surname) or ""

    aliases_set = set()

    def process_nick(nick_val: Any) -> None:
        nick = clean_text(nick_val)
        if nick:
            clean_nick = nick.strip('\'"')
            aliases_set.add(f'"{clean_nick}"')
            if surname and clean_nick.lower() not in surname.lower():
                aliases_set.add(f"{clean_nick} {surname}")

    for sub in getattr(record, "sub_records", []):
        if sub.tag == "NAME":
            alt_name = get_name(sub)
            if alt_name and alt_name != name and alt_name != "Unknown":
                aliases_set.add(alt_name)
            for name_sub in getattr(sub, "sub_records", []):
                if name_sub.tag == "NICK" and name_sub.value:
                    process_nick(name_sub.value)
                elif name_sub.tag in ("_AKA", "ALIA", "_NICK") and name_sub.value:
                    process_nick(name_sub.value)
                elif name_sub.tag == "NOTE" and name_sub.value:
                    note_val = clean_text(name_sub.value)
                    # If it's a short note directly under a NAME tag, it's often a nickname
                    if note_val and len(note_val.split()) <= 3:
                        process_nick(note_val)
        elif sub.tag == "NICK" and sub.value:
            process_nick(sub.value)
        elif sub.tag in ("_AKA", "ALIA", "_NICK") and sub.value:
            process_nick(sub.value)

    notes, source_ids = collect_record_notes_and_sources(record)

    filtered_notes = []
    excluded_short_notes = {"twin", "died young", "never married", "born dead", "stillborn", "unknown", "adopted"}
    for note in notes:
        note_lower = note.lower()
        val = None
        is_name_like = note.istitle() or len(note.split()) == 1
        
        if re.match(r"^(aka|nickname|also known as|goes by)\b", note_lower):
            val = re.sub(r"^(aka|nickname|also known as|goes by):?\s*", "", note, flags=re.IGNORECASE).strip()
        elif len(note.split()) <= 3 and is_name_like and not any(c in note for c in ".;:!?()") and note_lower not in excluded_short_notes:
            val = note.strip()
            
        if val:
            process_nick(val)
        else:
            filtered_notes.append(note)
            
    notes = filtered_notes

    aliases = sorted(list(aliases_set))

    birth_record = record.sub_tag("BIRT")
    death_record = record.sub_tag("DEAT")
    birth_date = normalize_text(get_event_date(birth_record))
    birth_place = normalize_text(get_event_place(birth_record))
    death_date = normalize_text(get_event_date(death_record))
    death_place = normalize_text(get_event_place(death_record))

    parents = []
    for fam_id in individual_to_famc.get(xref_id, []):
        family = families.get(fam_id)
        if not family:
            continue
        father_id = family_to_husb.get(fam_id)
        mother_id = family_to_wife.get(fam_id)
        if father_id:
            father_name = get_name(individuals.get(father_id))
            parents.append(f"Father: {father_name} ({father_id})")
        if mother_id:
            mother_name = get_name(individuals.get(mother_id))
            parents.append(f"Mother: {mother_name} ({mother_id})")

    spouses = []
    seen_spouses: set[str] = set()
    for fam_id in individual_to_fams.get(xref_id, []):
        family = families.get(fam_id)
        if not family:
            continue
        spouse_id = family_to_husb.get(fam_id) if family_to_husb.get(fam_id) != xref_id else family_to_wife.get(fam_id)
        if not spouse_id or spouse_id in seen_spouses:
            continue
        seen_spouses.add(spouse_id)
        spouse_name = get_name(individuals.get(spouse_id))
        marriage_record = family.sub_tag("MARR")
        marriage_date = get_event_date(marriage_record)
        marriage_place = get_event_place(marriage_record)
        divorce_record = family.sub_tag("DIV")
        divorce_date = get_event_date(divorce_record)
        divorce_place = get_event_place(divorce_record)
        spouse_line = (
            f"{spouse_name} ({spouse_id}) - Married: {marriage_date or 'Unknown'} | {marriage_place or 'Unknown'}"
        )
        if divorce_date:
            spouse_line += f" | Divorced: {divorce_date}"
            if divorce_place:
                spouse_line += f" in {divorce_place}"
        spouses.append(spouse_line)

    children_list = []
    seen_children: set[str] = set()
    for fam_id in individual_to_fams.get(xref_id, []):
        for child_id in family_to_children.get(fam_id, []):
            if child_id in seen_children:
                continue
            seen_children.add(child_id)
            child_name = get_name(individuals.get(child_id))
            children_list.append(f"{child_name} ({child_id})")

    timeline_entries = []
    for child_id in sorted(seen_children):
        child_record = individuals.get(child_id)
        if child_record is not None:
            birth_record = child_record.sub_tag("BIRT")
            if birth_record is not None:
                child_name = get_name(child_record)
                child_date = get_event_date(birth_record)
                child_place = get_event_place(birth_record)
                if child_date or child_place:
                    components = [child_date] if child_date else []
                    if child_place:
                        components.append(child_place)
                    timeline_entries.append(
                        f"Child born: {child_name} ({child_id})"
                        + (f" on {' | '.join(components)}" if components else "")
                    )

    for sub in record.sub_records:
        if sub.tag in IGNORE_INDI_TAGS:
            continue
        if sub.tag == "MARR":
            continue
        detail = clean_text(sub.value) if sub.value else None
        date = get_event_date(sub)
        place = get_event_place(sub)
        event_desc = describe_event(sub.tag, date, place, detail)
        if event_desc:
            timeline_entries.append(event_desc)

    for fam_id in individual_to_fams.get(xref_id, []):
        family = families.get(fam_id)
        if not family:
            continue
        marriage_record = family.sub_tag("MARR")
        divorce_record = family.sub_tag("DIV")
        if marriage_record:
            spouse_id = family_to_husb.get(fam_id) if family_to_husb.get(fam_id) != xref_id else family_to_wife.get(fam_id)
            spouse_name = get_name(individuals.get(spouse_id)) if spouse_id else "Unknown"
            marriage_date = get_event_date(marriage_record)
            marriage_place = get_event_place(marriage_record)
            timeline_entries.append(
                f"Married {spouse_name} ({spouse_id or 'Unknown'}) on {marriage_date or 'Unknown'}"
                + (f" in {marriage_place}" if marriage_place else "")
            )
        if divorce_record:
            spouse_id = family_to_husb.get(fam_id) if family_to_husb.get(fam_id) != xref_id else family_to_wife.get(fam_id)
            spouse_name = get_name(individuals.get(spouse_id)) if spouse_id else "Unknown"
            divorce_date = get_event_date(divorce_record)
            divorce_place = get_event_place(divorce_record)
            timeline_entries.append(
                f"Divorced {spouse_name} ({spouse_id or 'Unknown'}) on {divorce_date or 'Unknown'}"
                + (f" in {divorce_place}" if divorce_place else "")
            )

    source_summaries: list[str] = []
    seen_summaries: set[str] = set()
    for source_id in sorted(source_ids):
        source_record = sources.get(source_id)
        if source_record is None:
            continue
        summary = summarize_source_record(source_record)
        if summary not in seen_summaries:
            seen_summaries.add(summary)
            source_summaries.append(summary)

    timeline_entries = sorted(
        timeline_entries,
        key=lambda entry: (extract_year(entry) or 9999, entry),
    )

    return IndividualProfile(
        xref_id=xref_id,
        name=name,
        aliases=aliases,
        birth_date=birth_date,
        birth_place=birth_place,
        death_date=death_date,
        death_place=death_place,
        parents=parents,
        spouses=spouses,
        children=children_list,
        timeline=[entry for entry in timeline_entries if entry],
        notes=notes,
        sources=source_summaries,
    )


def extract_year(text: str) -> int | None:
    match = re.search(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def render_markdown(profile: IndividualProfile) -> str:
    lines = [
        f"# {profile.name}",
        "",
        "## Basic Info",
        f"- **Full name:** {profile.name}",
    ]

    if profile.aliases:
        lines.append(f"- **Also known as:** {', '.join(profile.aliases)}")

    lines.extend([
        f"- **GEDCOM ID:** {profile.xref_id}",
        f"- **Birth date:** {profile.birth_date}",
        f"- **Birth location:** {profile.birth_place}",
        f"- **Death date:** {profile.death_date}",
        f"- **Death location:** {profile.death_place}",
        "",
        "## Immediate Family",
        "**Parents:**",
    ])

    if profile.parents:
        lines.extend(f"- {parent}" for parent in profile.parents)
    else:
        lines.append("Unknown")

    lines.append("")
    lines.append("**Spouses:**")
    if profile.spouses:
        lines.extend(f"- {spouse}" for spouse in profile.spouses)
    else:
        lines.append("Unknown")

    lines.append("")
    lines.append("**Children:**")
    if profile.children:
        lines.extend(f"- {child}" for child in profile.children)
    else:
        lines.append("Unknown")

    lines.append("")
    lines.append("## Notes")
    if profile.notes:
        lines.extend(f"- {note}" for note in profile.notes)
    else:
        lines.append("No notes available.")

    if profile.sources:
        lines.append("")
        lines.append("## Sources")
        lines.extend(f"- {source}" for source in profile.sources)

    lines.append("")
    lines.append("## Biographical Timeline")
    if profile.timeline:
        lines.extend(f"- {event}" for event in profile.timeline)
    else:
        lines.append("No timeline events available.")

    return "\n".join(lines) + "\n"


def extract_root_id_from_gedcom(gedcom_path: Path) -> str | None:
    match = re.search(r"family_tree_filtered_([AI]\d+)\.ged", gedcom_path.name)
    if match:
        return match.group(1)
    return None


def get_profile_dir(gedcom_path: Path) -> Path:
    root_id = extract_root_id_from_gedcom(gedcom_path)
    if root_id:
        return gedcom_path.parent / f"profiles_{root_id}"
    return gedcom_path.parent / "profiles"


def write_profiles(gedcom_path: Path) -> Path:
    profile_dir = get_profile_dir(gedcom_path)
    if profile_dir.exists():
        shutil.rmtree(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    relationships = collect_relationships(gedcom_path)
    individuals = relationships["individuals"]
    families = relationships["families"]
    sources = relationships["sources"]
    individual_to_famc = relationships["individual_to_famc"]
    individual_to_fams = relationships["individual_to_fams"]
    family_to_husb = relationships["family_to_husb"]
    family_to_wife = relationships["family_to_wife"]
    family_to_children = relationships["family_to_children"]

    print(f"Generating {len(individuals)} profiles... this may take a moment.")

    for xref_id in sorted(individuals):
        profile = build_individual_profile(
            xref_id,
            individuals,
            families,
            sources,
            individual_to_famc,
            individual_to_fams,
            family_to_husb,
            family_to_wife,
            family_to_children,
        )
        filename = make_safe_filename(profile.name, profile.xref_id)
        file_path = profile_dir / filename
        file_path.write_text(render_markdown(profile), encoding="utf-8")
    
    return profile_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Markdown profiles from a GEDCOM file.")
    parser.add_argument("gedcom_path", help="Path to the filtered GEDCOM file.")
    args = parser.parse_args()

    gedcom_path = Path(args.gedcom_path)
    if not gedcom_path.exists():
        raise FileNotFoundError(f"GEDCOM file not found: {gedcom_path}")

    profile_dir = write_profiles(gedcom_path)
    print(f"Profiles generated in {profile_dir}")


if __name__ == "__main__":
    main()
