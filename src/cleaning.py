import pandas as pd
import numpy as np
import re
import duckdb

def clean_dataframe(df):
    """
    Fully dynamic universal cleaning engine for OmniPulse Analytics.
    Infers data types based on row content inspection (digit/letter ratios) 
    rather than hardcoded header whitelists or blacklists.
    """
    df_cleaned = df.copy()
    
    for col in df_cleaned.columns:
        col_lower = col.lower()
        
        # 1. Date Detection
        if 'date' in col_lower or 'time' in col_lower:
            df_cleaned[col] = pd.to_datetime(df_cleaned[col], format='mixed', errors='coerce')
            df_cleaned[col] = df_cleaned[col].dt.strftime('%Y-%m-%d')
            continue
            
        # 2. Dynamic Data Inspection (Zero Whitelists, Zero Blacklists)
        s = df_cleaned[col].astype(str)
        contains_digits_ratio = s.str.contains(r'\d').mean()
        contains_letters_ratio = s.str.contains(r'[a-zA-Z]').mean()
        
        # If 30%+ rows contain numbers and it's not predominantly text/alphanumeric codes (like SKUs)
        if contains_digits_ratio > 0.3 and contains_letters_ratio < 0.4:
            cleaned_numeric = []
            for val in df_cleaned[col]:
                if pd.isna(val):
                    cleaned_numeric.append(np.nan)
                    continue
                
                val_str = str(val).strip()
                if val_str.lower() == 'free':
                    cleaned_numeric.append(0.0)
                    continue
                
                # Strip everything except digits, dots, commas, and negative signs
                cleaned = re.sub(r'[^\d.,-]', '', val_str)
                if not cleaned:
                    cleaned_numeric.append(np.nan)
                    continue
                
                # Intelligent comma/dot handling for thousands separators vs decimals
                if ',' in cleaned and '.' in cleaned:
                    if cleaned.rfind(',') > cleaned.rfind('.'):
                        cleaned = cleaned.replace('.', '').replace(',', '.')
                    else:
                        cleaned = cleaned.replace(',', '')
                elif ',' in cleaned:
                    parts = cleaned.split(',')
                    if len(parts[-1]) == 2:
                        cleaned = cleaned.replace(',', '.')
                    else:
                        cleaned = cleaned.replace(',', '')
                
                try:
                    cleaned_numeric.append(float(cleaned))
                except:
                    cleaned_numeric.append(np.nan)
            
            df_cleaned[col] = pd.Series(cleaned_numeric, index=df_cleaned.index).abs()
            
            # Optional rounding for discrete counts if keywords appear
            discrete_keywords = ['qty', 'quantity', 'nights', 'stay', 'count', 'age', 'year', 'people']
            if any(k in col_lower for k in discrete_keywords):
                df_cleaned[col] = df_cleaned[col].round().astype('Int64')
        else:
            # Universal text fallback: Anything that fails the number profile safely becomes standardized text
            df_cleaned[col] = df_cleaned[col].astype(str).str.strip().str.upper()
            df_cleaned[col] = df_cleaned[col].replace(['NAN', 'NONE', 'NULL', ''], 'UNKNOWN')

    # 3. Drop completely empty rows
    df_cleaned = df_cleaned.dropna(how='all')
    return df_cleaned


def clean_dataset_with_duckdb(input_path, output_path):
    if str(input_path).lower().endswith('.csv'):
        df = pd.read_csv(input_path)
    elif str(input_path).lower().endswith(('.xls', '.xlsx')):
        df = pd.read_excel(input_path)
    else:
        df = duckdb.query(f"SELECT * FROM '{input_path}'").df()

    cleaned_df = clean_dataframe(df)
    
    if str(output_path).lower().endswith('.parquet'):
        cleaned_df.to_parquet(output_path, index=False)
    else:
        cleaned_df.to_csv(output_path, index=False)
        
    return output_path


def profile_dataframe(df):
    metrics = []
    dimensions = []
    
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            metrics.append(col)
        else:
            dimensions.append(col)
            
    profile_dict = {
        "Metrics": metrics,
        "Dimensions": dimensions
    }
    
    return df, profile_dict


def get_paginated_data(dataset_path, limit=100, offset=0):
    safe_path = str(dataset_path).replace("\\", "/")
    query = f"SELECT * FROM '{safe_path}' LIMIT {limit} OFFSET {offset}"
    return duckdb.query(query).df()