import pandas as pd
import numpy as np

class ConstraintExecutor:
    @staticmethod
    def execute_safely(df: pd.DataFrame, code: str) -> pd.DataFrame:
        """
        Executes LLM-generated code in a sanitized, lowercase environment.
        Protects historical data and restores original column casing after execution.
        """
        local_df = df.copy()

        original_column_map = {c.lower(): c for c in local_df.columns}
        local_df.columns = [c.lower() for c in local_df.columns]

        if 'date' in local_df.columns:
            local_df['date'] = pd.to_datetime(local_df['date'])
        
        # forecast mask
        forecast_mask = local_df['forecast'].notna()
        
        history_backup = local_df.loc[~forecast_mask, 'target'].copy() if 'target' in local_df.columns else None
        
        safe_globals = {
            "pd": pd, 
            "np": np, 
            "df": local_df, 
            "__builtins__": __builtins__ 
        }
        
        try:
            exec(code, safe_globals)
            modified_df = safe_globals.get("df")
            
            if 'target' in modified_df.columns:

                if history_backup is not None:
                    modified_df.loc[~forecast_mask, 'target'] = history_backup

                # Numeric Sanitization & Clipping
                modified_df.loc[forecast_mask, 'target'] = pd.to_numeric(
                    modified_df.loc[forecast_mask, 'target'], errors='coerce'
                ).fillna(0).clip(lower=0)
                
                modified_df = modified_df.rename(columns=original_column_map)

                # Dynamic Renaming: Adjustment X 
                existing_adj_count = len([c for c in modified_df.columns if "Adjustment" in str(c)])
                adj_name = f"Adjustment {existing_adj_count + 1}"
                
                modified_df[adj_name] = modified_df['target']
                modified_df = modified_df.drop(columns=['target'])
            
            if 'actual_combined' in modified_df.columns:
                modified_df = modified_df.drop(columns=['actual_combined'])
                
            return modified_df
            
        except Exception as e:
            raise RuntimeError(f"Constraint Execution Failed: {str(e)}")