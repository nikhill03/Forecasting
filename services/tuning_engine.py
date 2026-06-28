import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit, RandomizedSearchCV
from scipy.stats import randint, uniform, loguniform
import logging

logger = logging.getLogger("services.tuning_engine")

class TuningEngine:
    def __init__(self, n_iter=15, cv_splits=3, random_state=42):
        self.n_iter = n_iter
        self.cv_splits = cv_splits
        self.random_state = random_state

    def _get_search_space(self, model_name):

        if model_name == "LightGBM":
            return {
                "n_estimators": randint(100, 500),
                "learning_rate": loguniform(0.01, 0.1),
                "num_leaves": randint(15, 63),
                "max_depth": [-1, 5, 7, 10],
                "reg_alpha": uniform(0, 1),
                "reg_lambda": uniform(0, 1)
            }
        
        elif model_name == "XGBoost":
            return {
                "n_estimators": randint(100, 500),
                "learning_rate": loguniform(0.01, 0.1),
                "max_depth": randint(3, 10),
                "reg_alpha": uniform(0, 1),
                "reg_lambda": uniform(0, 1),
                "subsample": uniform(0.7, 0.3)  
            }
            
        elif model_name == "HistGB":
            return {
                "max_iter": randint(100, 500),
                "learning_rate": loguniform(0.01, 0.1),
                "max_depth": randint(3, 15),
                "l2_regularization": uniform(0, 1)
            }

        elif model_name in ["RandomForest", "ExtraTrees"]:
            return {
                "n_estimators": randint(100, 400),
                "max_depth": [None, 10, 20, 30],
                "min_samples_split": randint(2, 10),
                "min_samples_leaf": randint(1, 5)
            }
            
        elif model_name == "Ridge":
            return {
                "alpha": loguniform(0.1, 10.0)
            }

        elif model_name == "Huber":
            return {
                "epsilon": uniform(1.1, 0.8), 
                "alpha": loguniform(0.0001, 0.1)
            }

        return {}

    def optimize(self, model_name, estimator, X, y, default_params=None):
        min_samples = self.cv_splits + 2
        if len(X) < min_samples:
            return default_params if default_params else {}

        param_dist = self._get_search_space(model_name)
        
        if not param_dist:
            return default_params if default_params else {}

        tscv = TimeSeriesSplit(n_splits=self.cv_splits)

        search = RandomizedSearchCV(
            estimator=estimator,
            param_distributions=param_dist,
            n_iter=self.n_iter,
            cv=tscv,
            scoring="neg_mean_absolute_error", 
            n_jobs=1,
            random_state=self.random_state,
            verbose=0,
            error_score='raise' 
        )

        try:
            search.fit(X, y)
            best_params = search.best_params_
            print(f"      >> [Tuning] {model_name} found: {best_params}") # Debug
            return best_params
        except Exception as e:
            print(f"      >> [Tuning] {model_name} failed ({e}). Using defaults.")
            return default_params if default_params else {}