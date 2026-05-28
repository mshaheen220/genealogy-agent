# Gene E. - The Genealogy Agent

**Gene E. - The Genealogy Agent** is a knowledge-backed genealogy cleanup assistant for improving family trees using GEDCOM data, archival sources, and oral history.

---

## Overview

This project helps genealogists reconcile and clean family tree data by combining:

- **GEDCOM records** as the structured foundation  
- **archival material** as supporting evidence  
- **oral lore and remembered history** as contextual evidence  
- **retrieval and reconciliation workflows** to surface likely cleanup targets  

The goal is to support careful, evidence-based family history improvement rather than blindly auto-correcting records.

---

## Why this project exists

Genealogy cleanup is difficult because family trees often contain:

- duplicate or near-duplicate people  
- inconsistent dates and places  
- missing or weak relationships  
- spelling variants across records  
- conflicts between formal records and family memory  
- fragmented evidence spread across many sources  

**Gene E. - The Genealogy Agent** is designed to organize those signals, compare evidence, and support human review.

---

## Core goals

- Preserve GEDCOM as the structured backbone of the tree  
- Ingest archival sources and oral history as evidence  
- Normalize names, dates, places, and relationships  
- Retrieve relevant evidence for people, events, and relationships  
- Detect conflicts, duplicates, and cleanup opportunities  
- Present evidence and confidence clearly  
- Keep human approval in the loop before applying changes  

---

## Current architecture

This app is built as a **knowledge-grounded cleanup system**, not a generic autonomous agent.

### Main layers

1. **Data ingestion**
   - parse GEDCOM files  
   - ingest archival content  
   - ingest oral history notes and memory records  

2. **Normalization**
   - standardize names  
   - normalize dates and places  
   - structure person, family, and event relationships  

3. **Evidence layer**
   - attach provenance to every fact  
   - preserve source type  
   - preserve uncertainty and confidence  

4. **Retrieval**
   - search structured and unstructured evidence  
   - surface relevant source material for review  

5. **Reconciliation**
   - detect duplicate people  
   - compare conflicting facts  
   - suggest cleanup actions  

6. **Review workflow**
   - let users inspect, approve, or reject proposed changes  

---

## Key features

- GEDCOM-backed family tree foundation  
- archival and oral-history evidence ingestion  
- search and retrieval over structured and unstructured data  
- person and event summaries  
- duplicate and conflict detection  
- evidence-aware cleanup suggestions  
- provenance tracking  
- human-reviewed correction workflow  

---

## How it works

### Data flow

1. Load GEDCOM records and supporting evidence sources  
2. Normalize and structure the data  
3. Index archival and oral-history material  
4. Retrieve relevant evidence for queries and reconciliation checks  
5. Surface conflicts, duplicates, and suggested fixes  
6. Present those suggestions for human review and approval  

---

## Repository structure

- code

---

## Setup

### Requirements

- Python 3.x  
- Node.js  
- project dependencies from the Python and Node setup files  

### Python setup

- code

### Node setup

- code

---

## Running the app

### Run the processing pipeline

- code

### Start the search / API server

- code

---

## Data model

The app treats genealogy cleanup as an evidence problem:

- **structured facts** come from GEDCOM  
- **narrative evidence** comes from archives and oral lore  
- **proposed fixes** come from comparing evidence across sources  
- **accepted corrections** are tracked as reviewed changes  

This structure keeps cleanup grounded, explainable, and reviewable.

---

## Current focus

This project is centered on building a trustworthy genealogy cleanup workflow.

Current emphasis includes:

- structured GEDCOM foundation  
- evidence ingestion  
- retrieval and search  
- conflict detection  
- reviewable cleanup suggestions  

---

## Roadmap

### Near term
- improve normalization of names, dates, and places  
- expand evidence indexing  
- improve duplicate and conflict detection  

### Medium term
- strengthen reconciliation workflows  
- improve provenance visualization  
- improve evidence summaries for users  

### Longer term
- richer cleanup recommendations  
- stronger conflict review flows  
- more advanced genealogical reasoning over evidence  

---

## Principles

- Preserve source provenance  
- Treat oral lore as evidence, not certainty  
- Avoid overconfident automatic corrections  
- Keep humans in the loop  
- Explain why a suggestion was made  

---

## Example workflow

1. Load a GEDCOM into the app  
2. Search for a person, event, or relationship  
3. Retrieve relevant archival and oral-history evidence  
4. Review detected conflicts or duplicate profiles  
5. Accept, reject, or edit proposed cleanup actions  

---

## Notes on trust and evidence

Family history data is often incomplete and sometimes conflicting.  
This project is designed to support careful cleanup by showing evidence, uncertainty, and provenance instead of presenting uncertain conclusions as fact.

---

## Short summary

**Gene E. - The Genealogy Agent** is a genealogy cleanup assistant that combines GEDCOM structure with archival and oral-history evidence to support careful tree review, conflict detection, and evidence-backed reconciliation.