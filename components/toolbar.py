import dash_mantine_components as dmc
from dash import html, dcc
from dash_iconify import DashIconify

def create_toolbar():
    
    # Helper for clean upload buttons (Modern Chip Style)
    def clean_upload_btn(label, upload_id, filename_id, icon="carbon:document-add"):
        return dmc.Stack(gap=0, children=[
             dcc.Upload(
                id=upload_id,
                children=dmc.Group([
                    DashIconify(icon=icon, width=16, color="#1a73e8"), 
                    dmc.Text(label, size="sm", fw=600, c="#3c4043")
                ], gap="xs"),
                accept=".xlsx,.xls,.csv",
                multiple=False,
                style={
                    "padding": "8px 16px",
                    "borderRadius": "8px",
                    "border": "1px solid #e9ecef",
                    "backgroundColor": "#f8f9fa", # Soft background
                    "cursor": "pointer",
                    "transition": "all 0.2s ease",
                    "display": "flex",
                    "alignItems": "center"
                },
            ),
            dmc.Text(
                id=filename_id, 
                size="10px", 
                c="blue.6", 
                fw=500,
                style={
                    "maxWidth": "120px", 
                    "whiteSpace": "nowrap", 
                    "overflow": "hidden", 
                    "textOverflow": "ellipsis", 
                    "marginTop": "4px", 
                    "paddingLeft": "4px"
                }
            )
        ])

    return dmc.Paper(
        shadow="sm", 
        radius="lg",
        p="sm",
        mx="md", # Add margin to float it slightly
        style={
            "backgroundColor": "rgba(255, 255, 255, 0.9)", 
            "backdropFilter": "blur(10px)", # Glassmorphism effect
            "border": "1px solid #eaeaea",
            "position": "sticky", 
            "top": "80px", # Offset below header
            "zIndex": 99,
            "marginTop": "10px"
        },
        children=dmc.Group(
            justify="space-between",
            align="center",
            children=[
                
                # --- SECTION 1: DATA SOURCES ---
                dmc.Group(gap="lg", children=[
                    dmc.Stack(gap=2, children=[
                        dmc.Text("Upload Data ", size="10px", fw=700, c="dimmed", tt="uppercase"),
                        dmc.Group(gap="sm", children=[
                            clean_upload_btn("Target (Y)", "upload-target", "filename-target", "carbon:chart-line-data"),
                            clean_upload_btn("Features (X)", "upload-features", "filename-features", "carbon:data-1"),
                        ])
                    ]),
                ]),

                # --- SECTION 2: CONFIGURATION ---
                dmc.Group(gap="md", children=[
                    dmc.Divider(orientation="vertical", h=40, color="gray.2"),
                    dmc.Select(
                        id="select-sheet-target",
                        label="Worksheet",
                        placeholder="Select Sheet",
                        data=[],
                        disabled=True,
                        style={"width": 150},
                        size="xs",
                        radius="md",
                        variant="filled",
                        leftSection=DashIconify(icon="carbon:table", width=14, color="#1a73e8")
                    ),
                    dmc.Select(
                        id="select-col-target",
                        label="Target Metric",
                        placeholder="Select Column",
                        data=[],
                        disabled=True,
                        style={"width": 150},
                        size="xs",
                        radius="md",
                        variant="filled",
                        leftSection=DashIconify(icon="carbon:column", width=14, color="#1a73e8")
                    ),
                    dmc.NumberInput(
                        id="forecast-horizon-input",
                        label="Horizon (Days)",
                        value=60,
                        min=1, max=365,
                        style={"width": 100},
                        size="xs",
                        radius="md",
                        variant="filled",
                        leftSection=DashIconify(icon="carbon:time", width=14, color="#1a73e8")
                    ),
                ]),

                # --- SECTION 3: ACTIONS ---
                dmc.Group(gap="sm", children=[
                    dmc.Divider(orientation="vertical", h=40, color="gray.2"),
                    dmc.Button(
                        "Run Forecast",
                        id="run-models-btn",
                        # The .css gradient-button class will apply the indigo gradient
                        className="gradient-button",
                        leftSection=DashIconify(icon="carbon:play-filled", width=18),
                        size="sm",
                        radius="md",
                        px="xl",
                        style={"fontWeight": 700}
                    ),
                ])
            ]
        )
    )