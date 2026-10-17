# Genie setup: Bid Risk Assistant

Use this after the notebook `rfp_risk_pipeline.py` has run end to end. The cell in Step 3 prints which path produced the risk ratings. You want `ai_query`. If it printed the reference fallback, the Genie demo still works, but tell the interviewer honestly that the ratings came from a manual review.

---

## 1. Create the space

1. Sidebar → **Genie Agents** → **New**.
2. If asked for compute, pick the default serverless SQL warehouse.
3. Add these tables from `workspace` → `rfp_demo`:
   - `bid_risk_summary` (bid-level questions)
   - `clause_risk_register` (clause-level questions)
   - `bids` (bid master data)

   Leave out `rfp_clauses`, `clause_risk_ai` and `clause_risk_reference`. They are pipeline tables, and adding them gives Genie more ways to answer wrongly.

4. **Title:** Bid Risk Assistant
5. **Description:** Ask plain-English questions about commercial risk across the offshore services bid portfolio: which bids carry uncapped liability, where LD exposure is highest, and which open tenders need management approval before submission.

---

## 2. Instructions (paste into the Instructions / General instructions box)

```
You support a bid director at an offshore services contractor (ROV, subsea inspection, installation support, survey, decommissioning).

Business definitions:
- "Open bids" or "live bids" = bid_status IN ('Submitted', 'In Preparation').
- "Closed bids" = bid_status IN ('Won', 'Lost'). Win rate = Won / (Won + Lost); exclude No-Bid and open bids.
- Money is in USD millions. Always label answers "USD m".
- "High-risk clause" = risk_level = 'High'.
- "Uncapped" = is_uncapped = true (clause level) or liability_uncapped / ld_uncapped = true (bid level).
- "LD exposure" = max_ld_exposure_usd_m in bid_risk_summary. If ld_uncapped is true, say the exposure is uncapped rather than showing NULL or zero.
- "Needs management approval" = commercial_rag = 'Red'.
- "Riskiest" means highest risk_score unless the user says otherwise.

Table guidance:
- Use bid_risk_summary for any question about bids, clients, regions, portfolio totals or ratings.
- Use clause_risk_register only when the question is about specific clauses, clause categories, risk drivers or recommended actions.
- When listing bids, show tender_name, client_name, bid_status and the metric asked for. Do not show bid_id unless asked.
- When listing clauses, show tender_name, clause_category, risk_level, risk_driver and recommended_action. Show clause_text only if asked.

Style:
- Lead with a one-sentence answer, then the table.
- Round percentages and money to one decimal place.
- If a question cannot be answered from these tables (for example vessel availability or competitor pricing), say so plainly.
```

---

## 3. Sample questions (shown to users on the start screen)

- Which open bids need management approval before submission?
- What is our total LD exposure on open bids?
- Which clients consistently impose uncapped liability?
- Show high-risk clauses for the Mekong Basin Life-of-Field ROV 2026 bid with recommended actions
- Compare win rate for Red vs Green bids

---

## 4. Example SQL queries (add under SQL queries / Trusted queries)

Each one teaches Genie a pattern. Paste the question and the SQL.

**Q: Which open bids need management approval?**
```sql
SELECT tender_name, client_name, bid_status, contract_value_usd_m, high_risk_clauses,
       liability_uncapped, ld_uncapped, risk_score
FROM workspace.rfp_demo.bid_risk_summary
WHERE bid_status IN ('Submitted', 'In Preparation')
  AND commercial_rag = 'Red'
ORDER BY risk_score DESC
```

**Q: Win rate by commercial rating**
```sql
SELECT commercial_rag,
       COUNT_IF(bid_status = 'Won') AS won,
       COUNT_IF(bid_status = 'Lost') AS lost,
       ROUND(100 * COUNT_IF(bid_status = 'Won')
             / NULLIF(COUNT_IF(bid_status IN ('Won', 'Lost')), 0), 1) AS win_rate_pct
FROM workspace.rfp_demo.bid_risk_summary
GROUP BY commercial_rag
ORDER BY win_rate_pct DESC
```

**Q: Which clients impose the most high-risk terms?**
```sql
SELECT client_name, region,
       COUNT(DISTINCT bid_id) AS bids,
       SUM(CASE WHEN risk_level = 'High' THEN 1 ELSE 0 END) AS high_risk_clauses,
       ROUND(SUM(CASE WHEN risk_level = 'High' THEN 1 ELSE 0 END) / COUNT(DISTINCT bid_id), 1) AS high_risk_per_bid
FROM workspace.rfp_demo.clause_risk_register
GROUP BY client_name, region
ORDER BY high_risk_per_bid DESC
```

---

## 5. Test script (Day 5)

Ask each question in Genie. Check the answer against the SQL Editor, or by clicking **Show code** in Genie. Write down anything wrong, then fix it by adding an instruction or an example query, not by editing the data.

| # | Question | What a good answer looks like |
|---|---|---|
| 1 | How many bids did we submit in 2025? | Counts bids with 2025 submission dates. Check whether it includes No-Bid; it should ask or exclude. |
| 2 | Which open bids need management approval? | Only Submitted / In Preparation, Red only. |
| 3 | What's our total LD exposure on open bids? | Sums max_ld_exposure_usd_m and flags any open bid with uncapped LDs. |
| 4 | Which bids have uncapped liability? | Uses liability_uncapped, not just any uncapped clause. |
| 5 | Which region has the toughest commercial terms? | Average risk_score or high-risk clauses per bid by region. |
| 6 | Show me all payment terms longer than 60 days | Clause-level; finds the 120-day High-risk clauses. |
| 7 | Top 3 riskiest bids we actually won | Won bids by risk_score. Good story: won, but on bad terms. |
| 8 | Win rate for Red vs Green bids | Matches example query 2. |
| 9 | What should we push back on in the Al Rayyan Pipeline Inspection 2026 bid? | High-risk clauses with recommended_action. |
| 10 | Which clause category is most often high risk? | Group by clause_category on clause_risk_register. |
| 11 | How often does the AI agree with the expert review? | Uses ai_matches_expert. Your accuracy talking point. |
| 12 | What's the vessel day rate for this bid? | Should say it can't answer from these tables. |

---

## 6. Three-minute demo script (Day 6 recording)

1. **Problem (30 s):** "On a typical offshore bid, a commercial team reviews 100+ pages of terms by hand. Risk registers live in Excel, so nobody can see portfolio risk across 30 bids."
2. **Pipeline (40 s):** Show the notebook briefly. The clauses land in Unity Catalog, an LLM reviews each clause inside Databricks, and the output is a governed risk register. Show the accuracy cell.
3. **Genie (80 s):** Ask questions 2, 3 and 9 live. Click **Show code** once, so they see it produces real SQL against governed tables rather than a black box.
4. **Value (30 s):** Review time per bid falls from days to minutes. Management sees Red bids before submission. Every answer is traceable to a clause.

Be honest about the data: "The data is synthetic, modelled on my bid experience at Oceaneering. No client data was used."

---

## Troubleshooting

- **`ai_query` fails with an endpoint error:** run the endpoint-listing cell in Step 1, paste a chat model name (starts with `databricks-`) into `MODEL_ENDPOINT`, and rerun from Step 3.
- **Some clauses get NULL risk_level:** the model returned text that isn't valid JSON. The check cell below Step 3 lists them. Rerun Step 3; with temperature 0 this is usually only one or two clauses.
- **Genie uses the wrong table:** add one more example SQL query for that question pattern. Example queries fix wrong-table problems faster than more instruction text does.
- **Genie shows NULL LD exposure:** that bid has uncapped LDs. The instruction in section 2 tells Genie to say "uncapped". Check it was pasted in.
