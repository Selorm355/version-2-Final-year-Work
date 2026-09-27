import pandas as pd
import os
import uuid

def save_raw_upload(uploaded_file, temp_dir="temp_data"):
    """Reads the uploaded file and saves it immediately as a raw Parquet file."""
    file_id = str(uuid.uuid4())
    raw_path = os.path.join(temp_dir, f"raw_{file_id}.parquet")
    
    # Read the file and dump it straight to Parquet
    if uploaded_file.name.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)
        
    df.to_parquet(raw_path, index=False)
    
    return raw_path, file_id