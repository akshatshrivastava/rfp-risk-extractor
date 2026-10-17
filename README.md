# RFP Commercial Risk Register — Databricks + Genie

**Turn a stack of RFP contract clauses into a governed, portfolio-wide risk register, then let bid leaders ask plain-English questions about it.**

An LLM running inside Databricks reviews every commercial clause in a bid. It rates the risk to the contractor, explains the driver and recommends a negotiation or pricing response. The results land in Unity Catalog tables that a Genie space ("Bid Risk Assistant") can query in natural language.

> All clients, tenders and people in the data are fictional. Clause wording is modelled on typical offshore services contract terms and on my bid-management experience at Oceaneering. No client data was used.

---

## The business problem

On a typical offshore services bid, a commercial team reviews 100+ pages of contract terms by hand. The output is a risk register in Excel, one per bid, so:

- **Review is slow:** liquidated damages, liability caps, indemnities, payment terms and bonds are read clause by clause before every bid/no-bid decision.
- **Nobody sees portfolio risk:** leadership can't easily ask "which open bids carry uncapped liability?" across 30 live tenders.
- **Ratings are inconsistent:** two reviewers can rate the same clause differently, and there is no audit trail back to the clause text.

## What this demo does

| Step | What happens | Output |
|---|---|---|
| 1. Ingest | Three CSVs are loaded from a Unity Catalog volume into Delta tables | `bids`, `rfp_clauses`, `clause_risk_reference` |
| 2. AI clause review | `ai_query` sends each clause to an LLM with a commercial-review prompt and parses the JSON response | `clause_risk_ai`: risk level, risk driver, recommended action, cap as % of contract value, uncapped flag |
| 3. Business-ready tables | Clause ratings are joined to bid data and rolled up per bid | `clause_risk_register` (one row per clause), `bid_risk_summary` (one row per bid, 0–100 risk score, LD exposure in USD m, Red/Amber/Green rating) |
| 4. Semantic layer | Table and column descriptions are added so Genie understands business terms | Commented tables |
| 5. Accuracy check | AI ratings are compared with an expert reference review | % exact agreement, % within one level, agreement by clause category |
| 6. Genie space | Natural-language Q&A over the governed tables | "Bid Risk Assistant" |

## Architecture

```
CSV files ──► Unity Catalog volume ──► Delta tables
                                           │
                                 ai_query (LLM clause review)
                                           │
                        clause_risk_register ─► bid_risk_summary
                                           │
                               Genie space: "Bid Risk Assistant"
                                           │
                        Plain-English questions ─► SQL ─► answers
```

## Demo dataset

| | |
|---|---|
| Bids | 28 tenders (Jan 2025 – Oct 2026), USD 1,107 m total contract value |
| Bid status | 11 Won, 10 Lost, 4 Submitted, 1 In Preparation, 2 No-Bid |
| Regions | APAC, North America, MENA, Europe |
| Clauses | 286 commercial clauses across 14 categories |
| Categories | Liquidated Damages, Limitation of Liability, Indemnity, Consequential Loss, Payment Terms, Performance Bond, Retention, Currency & FX, Local Content, Governing Law & Disputes, Warranty, Force Majeure & Weather, Change Orders, Termination |
| Expert reference | 286 manual ratings (72 High, 111 Medium, 103 Low) used to check the AI |

## Risk logic

- **Clause risk:** *High* = uncapped exposure, liability well above market norms, or terms needing management approval. *Medium* = market-standard but needs a negotiation point or pricing allowance. *Low* = balanced or favourable to the contractor.
- **Bid risk score (0–100):** 0 means every clause is Low risk; 100 means every clause is High risk.
- **Commercial RAG:**
  - **Red:** uncapped liquidated damages, uncapped overall liability, or 5+ High-risk clauses. Needs management approval.
  - **Amber:** 3–4 High-risk clauses, or any other uncapped exposure.
  - **Green:** otherwise.
- **LD exposure (USD m)** = contract value × aggregate LD cap.

## Questions you can ask Genie

- Which open bids need management approval before submission?
- What is our total LD exposure on open bids?
- Which clients consistently impose uncapped liability?
- What should we push back on in the Al Rayyan Pipeline Inspection 2026 bid?
- Compare win rate for Red vs Green bids.
- How often does the AI agree with the expert review?

Every answer is real SQL against governed tables. Click **Show code** in Genie to trace it back to the clause.

## How to run it

Built and tested on **Databricks Free Edition** (serverless).

1. Import `rfp_risk_pipeline.py` as a notebook.
2. Run **Step 1** to create the schema `workspace.rfp_demo` and the volume `raw_files`. If the default model isn't available, the optional cell lists your model serving endpoints; set `MODEL_ENDPOINT` to one of them.
3. Upload `bids.csv`, `rfp_clauses.csv` and `clause_risk_reference.csv` to the volume (**Catalog → workspace → rfp_demo → Volumes → raw_files**).
4. Run the remaining cells top to bottom. Step 3 prints which path produced the ratings: `ai_query` (preferred), `ai_classify`, or the reference fallback.
5. Create the Genie space by following [`genie_setup.md`](genie_setup.md). It has the instructions text, sample questions, example SQL and a 12-question test script.

## Repository contents

| File | Purpose |
|---|---|
| `rfp_risk_pipeline.py` | Databricks notebook: ingest → AI clause review → risk register → Genie descriptions → accuracy check |
| `genie_setup.md` | Genie space configuration, instructions, example SQL, test script and 3-minute demo script |
| `bids.csv` | Bid master data: client, region, scope, contract type, value, status, target margin |
| `rfp_clauses.csv` | Commercial clause text by bid and category |
| `clause_risk_reference.csv` | Expert reference ratings used to measure AI accuracy |

## Tech stack

Databricks (Unity Catalog, Delta tables, serverless SQL) · Databricks AI Functions (`ai_query`, `ai_classify`) · Foundation Model serving (Llama 3.3 70B Instruct by default) · Genie · PySpark / Spark SQL

## Business value

- **Speed:** a first-pass commercial review of every clause in minutes instead of a manual read.
- **Visibility:** leadership sees Red bids, uncapped liability and LD exposure across the whole portfolio before submission.
- **Traceability:** every rating links to the clause text, the risk driver and a recommended action.
- **Trust:** AI ratings are checked against an expert reference, so you know where the model can be relied on and where it needs review.

## Author

**Akshat Shrivastava**, MBA (IPMX), IIM Lucknow. Previously managed commercial bids at Oceaneering International for clients including Saudi Aramco, ADNOC, Shell and TotalEnergies.
[LinkedIn](https://www.linkedin.com/in/akshatshrivastava808/)
