from __future__ import annotations

import argparse
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import DefaultDict

from ged4py import GedcomReader

INPUT_GEDCOM_PATH = Path("data/tree.ged")
OUTPUT_GEDCOM_PATH = Path("data/family_tree_filtered.ged")
ROOT_INDIVIDUAL_ID = "@I412076094635@"  # Replace this with your own root individual ID.


def make_output_path(root_individual_id: str) -> Path:
    normalized_id = root_individual_id.strip("@")
    return INPUT_GEDCOM_PATH.parent / f"family_tree_filtered_{normalized_id}.ged"

META_XREF_TAGS = {"SOUR", "OBJE", "SUBM", "REPO"}
XREF_PATTERN = re.compile(r"@[^@]+@")


def parse_gedcom_relationships(path: Path):
    individual_to_famc: DefaultDict[str, list[str]] = defaultdict(list)
    individual_to_fams: DefaultDict[str, list[str]] = defaultdict(list)
    family_to_husb: dict[str, str] = {}
    family_to_wife: dict[str, str] = {}
    family_to_children: DefaultDict[str, list[str]] = defaultdict(list)
    individual_ids: set[str] = set()
    family_ids: set[str] = set()

    with GedcomReader(str(path)) as reader:
        for record in reader.records0():
            if record.tag == "INDI":
                xref_id = record.xref_id
                individual_ids.add(xref_id)
                for sub in record.sub_records:
                    if sub.tag == "FAMC" and isinstance(sub.value, str):
                        individual_to_famc[xref_id].append(sub.value)
                    elif sub.tag == "FAMS" and isinstance(sub.value, str):
                        individual_to_fams[xref_id].append(sub.value)

            elif record.tag == "FAM":
                family_id = record.xref_id
                family_ids.add(family_id)
                for sub in record.sub_records:
                    if sub.tag == "HUSB" and isinstance(sub.value, str):
                        family_to_husb[family_id] = sub.value
                    elif sub.tag == "WIFE" and isinstance(sub.value, str):
                        family_to_wife[family_id] = sub.value
                    elif sub.tag == "CHIL" and isinstance(sub.value, str):
                        family_to_children[family_id].append(sub.value)

    return (
        individual_to_famc,
        individual_to_fams,
        family_to_husb,
        family_to_wife,
        family_to_children,
        individual_ids,
        family_ids,
    )


def collect_ancestors(root_id: str, individual_to_famc: dict[str, list[str]], family_to_husb: dict[str, str], family_to_wife: dict[str, str]):
    ancestor_ids: set[str] = set()
    ancestor_family_ids: set[str] = set()
    queue = deque([root_id])

    while queue:
        individual_id = queue.popleft()
        if individual_id in ancestor_ids:
            continue

        ancestor_ids.add(individual_id)
        for family_id in individual_to_famc.get(individual_id, []):
            ancestor_family_ids.add(family_id)
            father = family_to_husb.get(family_id)
            mother = family_to_wife.get(family_id)
            if father and father not in ancestor_ids:
                queue.append(father)
            if mother and mother not in ancestor_ids:
                queue.append(mother)

    return ancestor_ids, ancestor_family_ids


def collect_lateral_relations(ancestor_ids: set[str], individual_to_fams: dict[str, list[str]], family_to_husb: dict[str, str], family_to_wife: dict[str, str], family_to_children: dict[str, list[str]]):
    keep_individual_ids = set(ancestor_ids)
    keep_family_ids: set[str] = set()

    for ancestor_id in ancestor_ids:
        for family_id in individual_to_fams.get(ancestor_id, []):
            keep_family_ids.add(family_id)
            keep_individual_ids.update(family_to_children.get(family_id, []))

            spouse_id = family_to_husb.get(family_id)
            if spouse_id and spouse_id != ancestor_id:
                keep_individual_ids.add(spouse_id)

            spouse_id = family_to_wife.get(family_id)
            if spouse_id and spouse_id != ancestor_id:
                keep_individual_ids.add(spouse_id)

    return keep_individual_ids, keep_family_ids


def collect_descendant_relations(start_ids: set[str], individual_to_fams: dict[str, list[str]], family_to_children: dict[str, list[str]], family_to_husb: dict[str, str], family_to_wife: dict[str, str]):
    descendant_ids = set(start_ids)
    descendant_family_ids: set[str] = set()
    queue = deque(start_ids)

    while queue:
        individual_id = queue.popleft()
        for family_id in individual_to_fams.get(individual_id, []):
            if family_id in descendant_family_ids:
                continue
            descendant_family_ids.add(family_id)
            spouse_id = family_to_husb.get(family_id)
            if spouse_id and spouse_id != individual_id:
                descendant_ids.add(spouse_id)
            spouse_id = family_to_wife.get(family_id)
            if spouse_id and spouse_id != individual_id:
                descendant_ids.add(spouse_id)
            for child_id in family_to_children.get(family_id, []):
                if child_id not in descendant_ids:
                    descendant_ids.add(child_id)
                    queue.append(child_id)

    return descendant_ids, descendant_family_ids


def extract_top_level_blocks(lines: list[str]):
    blocks: list[tuple[str, int, int]] = []
    start = 0
    for idx, line in enumerate(lines):
        if line.startswith("0 ") and idx != start:
            blocks.append((lines[start], start, idx))
            start = idx
    blocks.append((lines[start], start, len(lines)))
    return blocks


def parse_block_header(first_line: str) -> tuple[str | None, str]:
    tokens = first_line.strip().split()
    if len(tokens) >= 3 and tokens[1].startswith("@") and tokens[1].endswith("@"):
        return tokens[1], tokens[2]
    if len(tokens) >= 2:
        return None, tokens[1]
    return None, ""


def normalize_root_id(root_id: str) -> str:
    raw = root_id.strip()
    if raw.startswith("@") and raw.endswith("@"):
        raw = raw[1:-1]
    if not raw.startswith("I"):
        raw = f"I{raw}"
    return f"@{raw}@"


def collect_meta_xrefs_for_kept_blocks(lines: list[str], keep_ids: set[str]):
    extra_xrefs: set[str] = set()
    blocks = extract_top_level_blocks(lines)
    for header, start, end in blocks:
        xref_id, tag = parse_block_header(header)
        if (xref_id and xref_id in keep_ids) or tag == "HEAD":
            for line in lines[start:end]:
                tokens = line.strip().split()
                if len(tokens) >= 3 and tokens[1] in META_XREF_TAGS:
                    candidate = tokens[2]
                    if XREF_PATTERN.fullmatch(candidate):
                        extra_xrefs.add(candidate)
    return extra_xrefs


def write_filtered_gedcom(input_path: Path, output_path: Path, keep_individual_ids: set[str], keep_family_ids: set[str], extra_xrefs: set[str], root_individual_id: str):
    keep_ids = keep_individual_ids | keep_family_ids | extra_xrefs
    lines = input_path.read_text(encoding="utf-8").splitlines(keepends=True)
    blocks = extract_top_level_blocks(lines)

    head_block = None
    trailer_block = None
    root_block = None
    kept_blocks: list[tuple[str, int, int]] = []

    for header, start, end in blocks:
        xref_id, tag = parse_block_header(header)
        if tag == "HEAD":
            head_block = (header, start, end)
            continue
        if tag == "TRLR":
            trailer_block = (header, start, end)
            continue
        if xref_id and xref_id in keep_ids:
            if xref_id == root_individual_id and tag == "INDI":
                root_block = (header, start, end)
            else:
                kept_blocks.append((header, start, end))

    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        if head_block is not None:
            _, start, end = head_block
            output_file.writelines(lines[start:end])

        if root_block is not None:
            _, start, end = root_block
            output_file.writelines(lines[start:end])

        for header, start, end in kept_blocks:
            output_file.writelines(lines[start:end])

        if trailer_block is not None:
            _, start, end = trailer_block
            output_file.writelines(lines[start:end])


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter GEDCOM to one root lineage.")
    parser.add_argument(
        "--root-id",
        default=ROOT_INDIVIDUAL_ID,
        help="Root individual ID, with or without @ signs and leading I.",
    )
    args = parser.parse_args()
    root_individual_id = normalize_root_id(args.root_id)

    (
        individual_to_famc,
        individual_to_fams,
        family_to_husb,
        family_to_wife,
        family_to_children,
        individual_ids,
        family_ids,
    ) = parse_gedcom_relationships(INPUT_GEDCOM_PATH)

    if root_individual_id not in individual_ids:
        raise ValueError(f"Root individual {root_individual_id} was not found in the GEDCOM file.")

    ancestor_ids, ancestor_family_ids = collect_ancestors(
        root_individual_id,
        individual_to_famc,
        family_to_husb,
        family_to_wife,
    )

    keep_individual_ids, lateral_family_ids = collect_lateral_relations(
        ancestor_ids,
        individual_to_fams,
        family_to_husb,
        family_to_wife,
        family_to_children,
    )

    descendant_ids, descendant_family_ids = collect_descendant_relations(
        ancestor_ids,
        individual_to_fams,
        family_to_children,
        family_to_husb,
        family_to_wife,
    )

    keep_individual_ids |= descendant_ids
    keep_family_ids = ancestor_family_ids | lateral_family_ids | descendant_family_ids

    raw_lines = INPUT_GEDCOM_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    extra_xrefs = collect_meta_xrefs_for_kept_blocks(raw_lines, keep_individual_ids | keep_family_ids)

    output_path = make_output_path(root_individual_id)
    write_filtered_gedcom(
        INPUT_GEDCOM_PATH,
        output_path,
        keep_individual_ids,
        keep_family_ids,
        extra_xrefs,
        root_individual_id,
    )
    print(f"Filtered GEDCOM written to: {output_path}")


if __name__ == "__main__":
    main()
