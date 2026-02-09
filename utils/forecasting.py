# utils/forecasting.py
import io
import base64
import pandas as pd
from typing import Dict

def parse_uploaded_data(contents: str) -> Dict[str, pd.DataFrame]:
    """
    Parse a base64-encoded uploaded Excel (or CSV) contents into a dict sheet -> DataFrame.
    """
    if not contents:
        return {}
    if "," in contents:
        _, content_string = contents.split(",", 1)
        decoded = base64.b64decode(content_string)
    else:
        decoded = contents if isinstance(contents, (bytes, bytearray)) else None
    if decoded is None:
        return {}
    try:
        xl = pd.ExcelFile(io.BytesIO(decoded))
        dfs = {s: xl.parse(s) for s in xl.sheet_names}
        return dfs
    except Exception:
        try:
            df = pd.read_csv(io.BytesIO(decoded))
            return {"Sheet1": df}
        except Exception:
            return {}
