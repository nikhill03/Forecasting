import pandas as pd
import numpy as np
import os
import sys
import matplotlib.pyplot as plt  # <--- NEW IMPORT

# Ensure we can import from the services module
sys.path.append(os.getcwd())

try:
    from services.forecasting_engine import ForecastingEngine
    from services.data_handling import DataHandling
except ImportError as e:
    print("❌ IMPORT ERROR: Could not import services.")
    print(f"Details: {e}")
    sys.exit(1)

def test_croston():
    print("==========================================")
    print("    🧪 CROSTON MODEL DIAGNOSTIC TEST      ")
    print("==========================================")
    
    # 1. SETUP FILE PATH
    filename = "Book.xlsx" 
    
    if not os.path.exists(filename):
        print(f"❌ FILE ERROR: Could not find '{filename}'")
        return

    # 2. LOAD DATA
    try:
        if filename.endswith(".xlsx") or filename.endswith(".xls"):
            print("   → Detected Excel file. Loading...")
            df = pd.read_excel(filename)
        else:
            print("   → Detected CSV/Text file. Loading...")
            df = pd.read_csv(filename)

        df.columns = df.columns.str.strip()
        
        # Auto-detect Date column
        date_col = "Date"
        metric_col = "Canceled" 
        
        for col in df.columns:
            if "date" in col.lower():
                date_col = col
                break
        
        if metric_col not in df.columns:
            print(f"❌ COLUMN ERROR: Metric '{metric_col}' not found.")
            return
            
        print(f"✅ Data Loaded. Metric: '{metric_col}'")
        
    except Exception as e:
        print(f"❌ LOAD ERROR: {e}")
        return

    # 3. PREPROCESS
    print("   → Preprocessing data...")
    dh = DataHandling()
    
    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
    df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()
    
    raw_series = df[metric_col]
    clean_series = dh.impute_train(raw_series)
    
    print(f"   → Data Points: {len(clean_series)}")
    print(f"   → Zero Count: {(clean_series == 0).sum()} ({(clean_series == 0).mean():.1%})")

    # 4. INITIALIZE ENGINE
    fe = ForecastingEngine()
    
    if not hasattr(fe, '_run_croston'):
        print("\n❌ ENGINE ERROR: '_run_croston' method not found.")
        return

    # 5. RUN MODEL
    print("\n🔄 Running Croston Model...")
    
    train, test = fe._train_test_split(clean_series)
    
    try:
        result = fe._run_croston(train, test)
        
        print("\n✅ MODEL EXECUTION SUCCESSFUL")
        print("-" * 30)
        print(f"WMAPE Score: {result.wmape:.4f}")
        print("-" * 30)
        
        # 6. GENERATE PLOT (NEW SECTION)
        # -----------------------------------------------------
        print("\n📈 Generating Plot...")
        
        plt.figure(figsize=(12, 6))
        
        # Plot History (Last 90 days for clarity)
        # You can remove .tail(90) to see full history
        plt.plot(train.index[-90:], train.tail(90), label='Training Data', color='blue', alpha=0.5)
        
        # Plot Actual Test Data
        plt.plot(test.index, test, label='Actual (Test)', color='green', linewidth=2)
        
        # Plot Croston Prediction (Test)
        plt.plot(result.predictions_test.index, result.predictions_test, 
                 label=f'Croston Test Pred (WMAPE: {result.wmape:.2f})', 
                 color='red', linestyle='--', linewidth=2)
        
        # Plot Future Forecast
        plt.plot(result.forecast.index, result.forecast, 
                 label='Future Forecast', color='orange', linestyle='--', linewidth=2)
        
        plt.title(f"Croston Model Analysis: {metric_col}")
        plt.xlabel("Date")
        plt.ylabel("Volume")
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        
        # Save to file
        output_file = "croston_plot.png"
        plt.savefig(output_file)
        print(f"✅ Plot saved to: {os.path.abspath(output_file)}")
        print("   (Open this file to view the graph)")
        
    except Exception as e:
        print(f"\n❌ EXECUTION ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_croston()