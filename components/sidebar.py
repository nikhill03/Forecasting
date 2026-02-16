from dash import html, dcc
import dash_mantine_components as dmc
from dash_iconify import DashIconify

def create_sidebar():

    # =========================================
    # SECTION 1: TARGET (Y) UPLOAD
    # =========================================
    target_section = dmc.Stack(
        gap="xs",
        children=[
            dmc.Text("Upload File", fw=700, size="sm", c="blue"),
            
            # Upload Y (Replaces old 'article-upload')
            dcc.Upload(
                id="upload-target",
                children=html.Div(
                    [
                        html.Div("⬆ Upload Target File"),
                        html.Div("(.xlsx, .csv)", style={"fontSize": "10px", "color": "#888"})
                    ]
                ),
                accept=".xlsx,.xls,.csv",
                multiple=False,
                style={
                    "width": "100%", "height": "50px", "lineHeight": "16px",
                    "borderWidth": "1.5px", "borderStyle": "dashed", "borderRadius": "6px",
                    "textAlign": "center", "cursor": "pointer", "backgroundColor": "#f0f9ff",
                    "display": "flex", "flexDirection": "column", "justifyContent": "center", "alignItems": "center"
                },
            ),
            dmc.Text(id="filename-target", size="xs", c="green", fw=500, style={"height": "18px"}),

            # Select Sheet Y (Old 'article-sheet-select' logic, renamed)
            dmc.Select(
                id="select-sheet-target",
                label="Select Process(s)",
                placeholder="Choose Process...",
                data=[],
                clearable=False,
                disabled=True,
                size="sm"
            ),

            # Select Column Y (Old 'metric-select' logic, strictly single select now)
            dmc.Select(
                id="select-col-target",
                label="Select Target Metric",
                placeholder="Choose column...",
                data=[],
                searchable=True,
                clearable=False,
                disabled=True,
                size="sm"
            ),
        ]
    )

    # =========================================
    # SECTION 2: FEATURES (X) UPLOAD
    # =========================================
    feature_section = dmc.Stack(
        gap="xs",
        children=[
            dmc.Divider(style={"marginTop": "8px", "marginBottom": "8px"}),
            dmc.Text("Add External Features (X)", fw=700, size="sm", c="orange"),
            
            # Upload X
            dcc.Upload(
                id="upload-features",
                children=html.Div(
                    [
                        html.Div("⬆ Upload Features File"),
                        html.Div("(.xlsx, .csv)", style={"fontSize": "10px", "color": "#888"})
                    ]
                ),
                accept=".xlsx,.xls,.csv",
                multiple=False,
                style={
                    "width": "100%", "height": "50px", "lineHeight": "16px",
                    "borderWidth": "1.5px", "borderStyle": "dashed", "borderRadius": "6px",
                    "textAlign": "center", "cursor": "pointer", "backgroundColor": "#fff8f0",
                    "display": "flex", "flexDirection": "column", "justifyContent": "center", "alignItems": "center"
                },
            ),
            dmc.Text(id="filename-features", size="xs", c="orange", fw=500, style={"height": "18px"}),
        ]
    )

    # =========================================
    # SECTION 3: CONFIGURATION (Kept your logic)
    # =========================================
    config_section = dmc.Stack(
        gap="xs",
        children=[
            dmc.Divider(style={"marginTop": "8px", "marginBottom": "8px"}),
            dmc.Text("Configuration", fw=700, size="sm", c="gray"),
            
            # Horizon Input (Moved into Stack)
            dmc.NumberInput(
                id="forecast-horizon-input",
                label="Forecast Horizon (Days)",
                value=60,
                min=7,
                max=365,
                step=1,
                size="xs",
                style={"marginTop": "5px"}
            )
        ]
    )

    # Controls
    controls = dmc.Group(
        gap="sm",
        children=[
            dmc.Button(
                "Run Models",
                id="run-models-btn",
                leftSection=DashIconify(icon="carbon:play-filled", width=14),
                color="blue",
                fullWidth=True, # Make it full width like the uploads
            ),
        ],
        style={"marginTop": "15px", "width": "100%"}
    )

    # Final Layout
    return dmc.Card(
        radius="sm",
        shadow="sm",
        withBorder=True,
        p="md",
        children=[
            target_section,
            feature_section,
            config_section, 
            controls,
            dmc.Text("", size="xs"),
        ],
        style={"width": "100%", "overflowY": "auto", "maxHeight": "90vh"},
    )