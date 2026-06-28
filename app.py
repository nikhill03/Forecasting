import logging
import warnings
import sys
import multiprocessing

import dash
import dash_mantine_components as dmc

import os
from dotenv import load_dotenv
load_dotenv()

from layout.main_layout import create_layout

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
logging.getLogger("prophet").setLevel(logging.WARNING)


# Suppress noisy warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

def create_app():
    app = dash.Dash(
        __name__,
        external_stylesheets=[
            "https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;800&display=swap", 
        ],
        suppress_callback_exceptions=True,
    )
    
    app.layout = dmc.MantineProvider(
        theme={
            "fontFamily": "'Plus Jakarta Sans', sans-serif",
            "primaryColor": "blue",
            "defaultRadius": "md",
        },
        children=[create_layout()],
    )
    return app


def main():
    app = create_app()
    
    from callbacks.file_callbacks import register_callbacks as register_file_callbacks
    from callbacks.processing import register_processing_callbacks
    
    register_file_callbacks(app)
    logger.info("File callbacks registered.")

    register_processing_callbacks(app)
    logger.info("Processing callbacks registered.")

    print(f"HF Token loaded: {'Yes' if os.getenv('HF_TOKEN') else 'No'}")

    app.run(debug=True, port=8080, use_reloader=False)

if __name__ == "__main__":
    main()