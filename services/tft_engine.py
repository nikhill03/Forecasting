import pandas as pd
import numpy as np
import torch

from pytorch_forecasting import (
    TimeSeriesDataSet,
    TemporalFusionTransformer,
)
from pytorch_forecasting.metrics import QuantileLoss
from pytorch_lightning import Trainer
from pytorch_lightning.callbacks import EarlyStopping

from utils.metrics import wmape


class TFTForecaster:
    """
    TFT wrapper aligned with MultivariateEngine contract
    """

    def __init__(self):
        self.max_encoder_length = 60
        self.max_prediction_length = 60
        self.min_rows = 180

    def _prepare_df(self, series: pd.Series) -> pd.DataFrame:
        df = pd.DataFrame({"y": series})
        df["time_idx"] = np.arange(len(df))
        df["series_id"] = 0

        idx = series.index
        df["day_of_week"] = idx.dayofweek
        df["month"] = idx.month
        df["is_month_end"] = idx.is_month_end.astype(int)

        return df.reset_index(drop=True)


    def run(self, series, split_idx, horizon):
        self.max_prediction_length = horizon

        if len(series) < self.min_rows:
            raise RuntimeError("TFT requires long history")

        df = self._prepare_df(series)

        train_df = df.iloc[:split_idx]
        test_df = df.iloc[split_idx:]

        training = TimeSeriesDataSet(
            train_df,
            time_idx="time_idx",
            target="y",
            group_ids=["series_id"],
            max_encoder_length=self.max_encoder_length,
            max_prediction_length=len(test_df),
            time_varying_known_reals=[
                "time_idx", "day_of_week", "month", "is_month_end"
            ],
            time_varying_unknown_reals=["y"],
        )

        validation = TimeSeriesDataSet.from_dataset(
            training, test_df, predict=True, stop_randomization=True
        )

        train_loader = training.to_dataloader(train=True, batch_size=32)
        val_loader = validation.to_dataloader(train=False, batch_size=32)

        tft = TemporalFusionTransformer.from_dataset(
            training,
            learning_rate=0.03,
            hidden_size=16,
            attention_head_size=2,
            dropout=0.1,
            loss=QuantileLoss(),
        )

        trainer = Trainer(
            max_epochs=20,
            accelerator="cpu",
            callbacks=[EarlyStopping(monitor="val_loss", patience=3)],
            logger=False,
            enable_checkpointing=False,
        )

        trainer.fit(tft, train_loader, val_loader)

        preds = tft.predict(val_loader).numpy().flatten()
        y_test = test_df["y"].values

        test_pred = pd.Series(
            preds,
            index=series.index[split_idx:]
        )

        score = wmape(y_test, preds)
        accuracy = round((1 - score) * 100, 2)

        # ---- REFIT ON FULL DATA ----
        full_ds = TimeSeriesDataSet(
            df,
            time_idx="time_idx",
            target="y",
            group_ids=["series_id"],
            max_encoder_length=self.max_encoder_length,
            max_prediction_length=self.max_prediction_length,
            time_varying_known_reals=[
                "time_idx", "day_of_week", "month", "is_month_end"
            ],
            time_varying_unknown_reals=["y"],
        )

        full_loader = full_ds.to_dataloader(train=False, batch_size=32)

        future_preds = tft.predict(full_loader).numpy().flatten()[-self.max_prediction_length:]

        forecast_idx = pd.date_range(
            start=series.index.max() + pd.Timedelta(days=1),
            periods=self.max_prediction_length,
            freq="D",
        )

        forecast = pd.Series(future_preds, index=forecast_idx)

        return {
            "test_pred": test_pred,
            "forecast": forecast,
            "best_model": "TFT",
            "wmape": score,
            "accuracy": accuracy,
            "model": tft,
            "top_features": ["sequence"],
        }

