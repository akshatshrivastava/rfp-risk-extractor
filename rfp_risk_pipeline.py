# Databricks notebook source
# MAGIC %md
# MAGIC # RFP Commercial Risk Register — Databricks + Genie demo
# MAGIC
# MAGIC **What this notebook does**
# MAGIC 1. Loads three CSVs (bids, RFP clauses, expert reference ratings) from a Unity Catalog volume into tables.
# MAGIC 2. Uses an LLM *inside Databricks* (`ai_query`) to read every clause and return a risk level, risk driver, recommended action and any cap / amount as % of contract value.
# MAGIC 3. Builds two business-ready tables for Genie: `clause_risk_register` (one row per clause) and `bid_risk_summary` (one row per bid, with a Red / Amber / Green rating).
# MAGIC 4. Adds table and column descriptions so Genie understands the business terms.
# MAGIC 5. Measures how often the AI agrees with the expert reference rating.
# MAGIC
# MAGIC All clients, tenders and people in the data are fictional. Clause wording is modelled on typical offshore services contract terms.
# MAGIC
# MAGIC **Run order:** run cells top to bottom. Step 2 asks you to upload the CSVs once.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1 — Configuration

# COMMAND ----------

CATALOG = "workspace"   # default catalog in Databricks Free Edition
SCHEMA = "rfp_demo"
VOLUME = "raw_files"

# Chat model used by ai_query. Run the next cell to see which endpoints your workspace has,
# then paste one of the names here if this default is not in the list.
MODEL_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct"

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{VOLUME}")
spark.sql(f"USE {CATALOG}.{SCHEMA}")
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
print("Upload the three CSV files to:", VOLUME_PATH)

# COMMAND ----------

# Optional: list the model serving endpoints available to you (chat models start with "databricks-").
try:
    from mlflow.deployments import get_deploy_client
    eps = [e["name"] for e in get_deploy_client("databricks").list_endpoints()]
    print("\n".join(sorted(eps)))
except Exception as e:
    print("Could not list endpoints from the notebook; check the 'Serving' page in the sidebar instead.\n", e)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2 — Upload the CSVs (one time)
# MAGIC
# MAGIC In the left sidebar: **Catalog → workspace → rfp_demo → Volumes → raw_files → Upload to this volume**, then upload:
# MAGIC - `bids.csv`
# MAGIC - `rfp_clauses.csv`
# MAGIC - `clause_risk_reference.csv`
# MAGIC
# MAGIC Then run the next cell.

# COMMAND ----------

for t in ["bids", "rfp_clauses", "clause_risk_reference"]:
    spark.sql(f"""
        CREATE OR REPLACE TABLE {t} AS
        SELECT * FROM read_files('{VOLUME_PATH}/{t}.csv',
                                 format => 'csv', header => true, inferSchema => true,
                                 multiLine => true, escape => '"')
    """)
    print(t, spark.table(t).count(), "rows")

# Fix types explicitly so Genie sees clean columns
spark.sql("""
CREATE OR REPLACE TABLE bids AS
SELECT bid_id, tender_name, client_name, country, region, scope_of_work, contract_type,
       CAST(contract_value_usd_m AS DOUBLE) AS contract_value_usd_m,
       CAST(submission_date AS DATE)        AS submission_date,
       bid_status, bid_manager,
       CAST(target_margin_pct AS DOUBLE)    AS target_margin_pct
FROM bids
""")
display(spark.table("bids").limit(5))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3 — AI clause review with `ai_query`
# MAGIC
# MAGIC Every clause is sent to the LLM with a commercial-review prompt. The model returns JSON, which we parse into columns.
# MAGIC If `ai_query` is not available on your workspace, the cell falls back to `ai_classify`, and as a last resort to the expert reference
# MAGIC (it prints which path it used, so you know what you are demoing).

# COMMAND ----------

PROMPT = (
    "You are a senior commercial manager reviewing an RFP clause for an offshore services contractor (the Contractor). "
    "Rate the commercial risk TO THE CONTRACTOR versus normal offshore industry terms. "
    "Rules: High = unlimited or uncapped exposure, liability well above market norms, or terms that need management approval. "
    "Medium = market-standard but needs a negotiation point or pricing allowance. Low = balanced or favourable to the Contractor. "
    "Return ONLY a JSON object with these keys: "
    "risk_level (High, Medium or Low), "
    "risk_driver (max 12 words, the main reason), "
    "recommended_action (max 15 words, the negotiation or pricing response), "
    "pct_of_contract_value (number: the aggregate cap or amount stated as a percent of the Contract Price, e.g. LD cap, liability cap, bond, retention; 0 if none applies such as no retention; null if the clause states no percentage), "
    "is_uncapped (true if the clause exposes the Contractor to liability with no limit, else false). "
    "Clause category: "
)

def ai_query_sql(with_params: bool) -> str:
    params = ", modelParameters => named_struct('temperature', 0.0, 'max_tokens', 300)" if with_params else ""
    return f"""
    CREATE OR REPLACE TABLE clause_risk_ai AS
    WITH raw AS (
      SELECT clause_id,
             ai_query('{MODEL_ENDPOINT}',
                      concat('{PROMPT}', clause_category, '. Clause text: ', clause_text){params}) AS response
      FROM rfp_clauses
    ),
    parsed AS (
      SELECT clause_id, response,
             from_json(regexp_extract(response, '(?s)[{{].*[}}]', 0),
                       'risk_level STRING, risk_driver STRING, recommended_action STRING, pct_of_contract_value DOUBLE, is_uncapped BOOLEAN') AS j
      FROM raw
    )
    SELECT clause_id,
           initcap(trim(j.risk_level))   AS ai_risk_level,
           j.risk_driver                 AS ai_risk_driver,
           j.recommended_action          AS ai_recommended_action,
           j.pct_of_contract_value       AS ai_pct_of_contract_value,
           coalesce(j.is_uncapped, false) AS ai_is_uncapped,
           '{MODEL_ENDPOINT}'            AS ai_model,
           response                      AS ai_raw_response
    FROM parsed
    """

AI_SOURCE = None
for label, sql in [("ai_query (with params)", ai_query_sql(True)), ("ai_query", ai_query_sql(False))]:
    try:
        spark.sql(sql)
        AI_SOURCE = label
        break
    except Exception as e:
        print(f"{label} failed: {str(e)[:300]}")

if AI_SOURCE is None:
    try:
        spark.sql("""
        CREATE OR REPLACE TABLE clause_risk_ai AS
        SELECT c.clause_id,
               ai_classify(concat('Risk to an offshore contractor of this ', c.clause_category, ' clause: ', c.clause_text),
                           array('High', 'Medium', 'Low'))   AS ai_risk_level,
               r.risk_driver                                 AS ai_risk_driver,
               r.recommended_action                          AS ai_recommended_action,
               CAST(r.pct_of_contract_value AS DOUBLE)       AS ai_pct_of_contract_value,
               CAST(r.is_uncapped AS BOOLEAN)                AS ai_is_uncapped,
               'ai_classify'                                 AS ai_model,
               CAST(NULL AS STRING)                          AS ai_raw_response
        FROM rfp_clauses c JOIN clause_risk_reference r USING (clause_id)
        """)
        AI_SOURCE = "ai_classify (risk level only; other fields from reference)"
    except Exception as e:
        print("ai_classify failed:", str(e)[:300])

if AI_SOURCE is None:
    spark.sql("""
    CREATE OR REPLACE TABLE clause_risk_ai AS
    SELECT clause_id,
           expert_risk_level                       AS ai_risk_level,
           risk_driver                             AS ai_risk_driver,
           recommended_action                      AS ai_recommended_action,
           CAST(pct_of_contract_value AS DOUBLE)   AS ai_pct_of_contract_value,
           CAST(is_uncapped AS BOOLEAN)            AS ai_is_uncapped,
           'reference (no AI available)'           AS ai_model,
           CAST(NULL AS STRING)                    AS ai_raw_response
    FROM clause_risk_reference
    """)
    AI_SOURCE = "reference fallback - AI functions not available on this workspace"

print("Risk ratings produced by:", AI_SOURCE)
display(spark.sql("SELECT ai_risk_level, count(*) AS clauses FROM clause_risk_ai GROUP BY 1 ORDER BY 1"))

# COMMAND ----------

# Any clause the model failed to rate? (parse errors show up as NULL ai_risk_level)
display(spark.sql("""
SELECT c.clause_id, c.clause_category, a.ai_raw_response
FROM clause_risk_ai a JOIN rfp_clauses c USING (clause_id)
WHERE a.ai_risk_level IS NULL OR a.ai_risk_level NOT IN ('High','Medium','Low')
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4 — Business-ready tables for Genie

# COMMAND ----------

spark.sql("""
CREATE OR REPLACE TABLE clause_risk_register AS
SELECT b.bid_id, b.tender_name, b.client_name, b.country, b.region, b.scope_of_work,
       b.contract_type, b.bid_status, b.submission_date, b.contract_value_usd_m, b.bid_manager,
       c.clause_id, c.section_ref, c.clause_category, c.clause_text,
       a.ai_risk_level            AS risk_level,
       a.ai_risk_driver           AS risk_driver,
       a.ai_recommended_action    AS recommended_action,
       a.ai_pct_of_contract_value AS pct_of_contract_value,
       a.ai_is_uncapped           AS is_uncapped,
       CASE a.ai_risk_level WHEN 'High' THEN 3 WHEN 'Medium' THEN 2 WHEN 'Low' THEN 1 END AS risk_points,
       r.expert_risk_level,
       (a.ai_risk_level = r.expert_risk_level) AS ai_matches_expert,
       a.ai_model
FROM rfp_clauses c
JOIN bids b                       USING (bid_id)
JOIN clause_risk_ai a             USING (clause_id)
LEFT JOIN clause_risk_reference r USING (clause_id)
""")

spark.sql("""
CREATE OR REPLACE TABLE bid_risk_summary AS
WITH agg AS (
  SELECT bid_id,
         count(*)                                                    AS clauses_reviewed,
         sum(CASE WHEN risk_level = 'High'   THEN 1 ELSE 0 END)      AS high_risk_clauses,
         sum(CASE WHEN risk_level = 'Medium' THEN 1 ELSE 0 END)      AS medium_risk_clauses,
         sum(CASE WHEN risk_level = 'Low'    THEN 1 ELSE 0 END)      AS low_risk_clauses,
         round(100 * (sum(risk_points) - count(*)) / (2 * count(*)), 0) AS risk_score,
         max(CASE WHEN clause_category = 'Liquidated Damages'      THEN pct_of_contract_value END) AS ld_cap_pct,
         max(CASE WHEN clause_category = 'Liquidated Damages'      THEN CAST(is_uncapped AS INT) END) = 1 AS ld_uncapped,
         max(CASE WHEN clause_category = 'Limitation of Liability' THEN pct_of_contract_value END) AS liability_cap_pct,
         max(CASE WHEN clause_category = 'Limitation of Liability' THEN CAST(is_uncapped AS INT) END) = 1 AS liability_uncapped,
         max(CASE WHEN clause_category = 'Performance Bond'        THEN pct_of_contract_value END) AS performance_bond_pct,
         max(CASE WHEN clause_category = 'Retention'               THEN pct_of_contract_value END) AS retention_pct,
         sum(CASE WHEN is_uncapped THEN 1 ELSE 0 END)                AS uncapped_clauses
  FROM clause_risk_register
  GROUP BY bid_id
)
SELECT b.bid_id, b.tender_name, b.client_name, b.country, b.region, b.scope_of_work, b.contract_type,
       b.bid_status, b.submission_date, b.contract_value_usd_m, b.target_margin_pct, b.bid_manager,
       a.clauses_reviewed, a.high_risk_clauses, a.medium_risk_clauses, a.low_risk_clauses, a.risk_score,
       a.ld_cap_pct,
       round(b.contract_value_usd_m * a.ld_cap_pct / 100, 2)        AS max_ld_exposure_usd_m,
       coalesce(a.ld_uncapped, false)                               AS ld_uncapped,
       a.liability_cap_pct,
       coalesce(a.liability_uncapped, false)                        AS liability_uncapped,
       a.performance_bond_pct, a.retention_pct, a.uncapped_clauses,
       CASE WHEN coalesce(a.liability_uncapped, false) OR coalesce(a.ld_uncapped, false)
                 OR a.high_risk_clauses >= 5                         THEN 'Red'
            WHEN a.high_risk_clauses >= 3 OR a.uncapped_clauses > 0  THEN 'Amber'
            ELSE 'Green' END                                        AS commercial_rag
FROM bids b JOIN agg a USING (bid_id)
""")

display(spark.sql("SELECT tender_name, bid_status, high_risk_clauses, risk_score, commercial_rag FROM bid_risk_summary ORDER BY risk_score DESC"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5 — Describe the data for Genie
# MAGIC Genie reads these descriptions when it writes SQL. Good descriptions are the single biggest factor in answer quality.

# COMMAND ----------

TABLE_COMMENTS = {
    "bids": "One row per tender the offshore services contractor bid for (or chose not to bid). Fictional demo data.",
    "clause_risk_register": "One row per commercial clause in an RFP, with an AI-generated risk rating (High/Medium/Low), risk driver and recommended negotiation action. Use this for clause-level questions.",
    "bid_risk_summary": "One row per bid with clause risk counts, a 0-100 risk score, key commercial caps and a Red/Amber/Green commercial rating. Use this for bid-level and portfolio questions.",
}
COLUMN_COMMENTS = {
    "contract_value_usd_m": "Estimated contract value in millions of US dollars",
    "bid_status": "Won, Lost, Submitted (awaiting award), In Preparation (not yet submitted) or No-Bid (declined to bid). Open bids = Submitted or In Preparation.",
    "region": "MENA, APAC, Europe or North America",
    "clause_category": "Commercial topic of the clause, e.g. Liquidated Damages, Limitation of Liability, Indemnity, Payment Terms",
    "risk_level": "AI-assessed commercial risk to the contractor: High, Medium or Low",
    "risk_driver": "Short reason for the risk rating",
    "recommended_action": "Suggested negotiation or pricing response",
    "pct_of_contract_value": "Cap or amount in the clause as a percent of contract price (LD cap, liability cap, bond, retention). NULL if not applicable.",
    "is_uncapped": "True when the clause exposes the contractor to unlimited liability",
    "risk_points": "High = 3, Medium = 2, Low = 1",
    "risk_score": "0-100 bid risk score: 0 = every clause Low risk, 100 = every clause High risk",
    "ld_cap_pct": "Aggregate liquidated damages cap as percent of contract price",
    "max_ld_exposure_usd_m": "Maximum liquidated damages exposure in USD millions = contract value x LD cap",
    "liability_cap_pct": "Overall limitation of liability as percent of contract price",
    "commercial_rag": "Red = uncapped LDs or uncapped overall liability, or 5+ High-risk clauses; Amber = 3-4 High-risk clauses or any other uncapped exposure; Green = otherwise",
    "expert_risk_level": "Reference rating from a manual commercial review, used to check AI accuracy",
    "ai_matches_expert": "True when the AI risk level equals the expert reference rating",
}
for t, c in TABLE_COMMENTS.items():
    spark.sql(f"COMMENT ON TABLE {t} IS '{c}'")
    cols = [f.name for f in spark.table(t).schema.fields]
    for col, cc in COLUMN_COMMENTS.items():
        if col in cols:
            spark.sql(f"ALTER TABLE {t} ALTER COLUMN {col} COMMENT '{cc}'")
print("Descriptions added.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6 — How accurate is the AI? (your best presales talking point)

# COMMAND ----------

display(spark.sql("""
SELECT round(100 * avg(CAST(ai_matches_expert AS INT)), 1) AS pct_exact_agreement,
       round(100 * avg(CASE WHEN abs(risk_points - CASE expert_risk_level WHEN 'High' THEN 3 WHEN 'Medium' THEN 2 ELSE 1 END) <= 1
                            THEN 1 ELSE 0 END), 1)          AS pct_within_one_level,
       count(*)                                             AS clauses
FROM clause_risk_register
"""))

display(spark.sql("""
SELECT clause_category,
       round(100 * avg(CAST(ai_matches_expert AS INT)), 0) AS pct_agreement,
       count(*) AS clauses
FROM clause_risk_register
GROUP BY 1 ORDER BY pct_agreement
"""))

# COMMAND ----------

# Where AI and expert disagree - read a few of these; they make good interview stories
display(spark.sql("""
SELECT tender_name, clause_category, clause_text, risk_level AS ai_rating, expert_risk_level, risk_driver
FROM clause_risk_register
WHERE NOT ai_matches_expert
ORDER BY clause_category
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Next: create the Genie space
# MAGIC Sidebar → **Genie Agents → New**, add `bid_risk_summary`, `clause_risk_register` and `bids` from `workspace.rfp_demo`,
# MAGIC then follow `genie_setup.md` for the instructions text, sample questions and test script.
