import os
import json
import re
import duckdb

def extract_json(raw_text: str) -> dict:
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    return json.loads(raw_text)

def generate_virtual_metric(client, user_prompt, profile):
    """
    Translates a user's natural language metric description into a DuckDB SQL expression.
    """
    system_prompt = f"""
    You are the calculation engine for OmniPulse Analytics.
    Available schema: {json.dumps(profile)}
    
    The user will describe a custom metric they want to calculate.
    Your job is to translate that into a valid DuckDB SQL mathematical expression using ONLY the available columns.
    
    Rules:
    1. ONLY return the mathematical expression, NOT a full SELECT statement.
    2. Wrap column names in double quotes.
    3. Use COALESCE("col_name", 0.0) for all math to prevent NULL/Float type mismatch errors.
    4. Return ONLY a single JSON object.
    
    JSON Schema:
    {{
        "formula": "The SQL expression (e.g., COALESCE(\"Revenue\", 0.0) - COALESCE(\"Cost\", 0.0))",
        "name": "A short, professional name for the metric (e.g., 'Net Profit')",
        "error": "If the request is impossible or references missing columns, explain why here. Otherwise, null."
    }}
    """
    
    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        return extract_json(response.choices[0].message.content.strip())
    except Exception as e:
        return {"error": f"LLM Generation failed: {str(e)}", "formula": None, "name": None}

def validate_formula(parquet_path, formula_str):
    """
    Executes a zero-impact 'dry run' to verify the formula won't crash the database.
    Does NOT mutate the original dataset.
    """
    con = duckdb.connect()
    try:
        # Run the formula on just 1 row to test syntax and type compatibility
        query = f"SELECT ({formula_str}) AS test_col FROM '{parquet_path}' LIMIT 1"
        con.execute(query).df()
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        con.close()