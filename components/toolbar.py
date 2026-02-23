import dash_mantine_components as dmc
from dash import html, dcc
from dash_iconify import DashIconify

def create_toolbar():
    
    # Helper for clean upload buttons (Modern Chip Style)
    def clean_upload_btn(label, upload_id, filename_id, icon="carbon:document-add"):
        return dmc.Box( 
            style={
                "position": "relative", 
                "paddingBottom": "16px",
                "display": "flex", 
                "flexDirection": "column", 
                "alignItems": "center",
                "justifyContent": "center"
            }, 
            children=[
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
                        "backgroundColor": "#f8f9fa",
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
                        "position": "absolute", 
                        "bottom": "-4px",
                        "left": "4px",
                        "maxWidth": "140px", 
                        "whiteSpace": "nowrap", 
                        "overflow": "hidden", 
                        "textOverflow": "ellipsis",
                    }
                )
            ]
        )

    return dmc.Paper(
        shadow="sm", 
        radius=0,        # FIXED: Removed radius for full-width look
        p="xs",     
        mx=0,            # FIXED: Removed horizontal margins
        style={
            "backgroundColor": "rgba(255, 255, 255, 0.9)", 
            "backdropFilter": "blur(10px)",
            "borderBottom": "1px solid #eaeaea", # Border only on bottom for seamless flow
            "position": "sticky", 
            "top": "70px", # Matches your header height
            "zIndex": 99,
            "marginTop": "0px",
            "width": "100%" # Ensures it stretches to screen edges
        },
        children=dmc.Container( # Container inside to maintain content alignment
            fluid=True,
            px="xl", # Matches the padding of your Header
            children=dmc.Group(
                justify="space-between",
                align="center",
                children=[
                    
                    # --- SECTION 1: DATA SOURCES ---
                    dmc.Group(
                        gap="lg", 
                        children=[
                            dmc.Group(
                                gap="sm", 
                                align="center",
                                children=[
                                    clean_upload_btn("Upload Target (Y)", "upload-target", "filename-target", "carbon:chart-line-data"),
                                    clean_upload_btn("Upload Features (X)", "upload-features", "filename-features", "carbon:data-1"),
                                ]
                            )
                        ]
                    ),

                    # --- SECTION 2: CONFIGURATION ---
                    dmc.Group(gap="md", align="center", children=[
                        dmc.Divider(orientation="vertical", h=32, color="gray.2"),
                        dmc.Select(
                            id="select-sheet-target",
                            placeholder="Select Worksheet",
                            data=[],
                            disabled=True,
                            style={"width": 170},
                            size="sm",
                            radius="md",
                            variant="filled",
                            leftSection=DashIconify(icon="carbon:table", width=14, color="#1a73e8")
                        ),
                        dmc.Select(
                            id="select-col-target",
                            placeholder="Select Target Metric",
                            data=[],
                            disabled=True,
                            style={"width": 180},
                            size="sm",
                            radius="md",
                            variant="filled",
                            leftSection=DashIconify(icon="carbon:column", width=14, color="#1a73e8")
                        ),
                        dmc.NumberInput(
                            id="forecast-horizon-input",
                            placeholder="Horizon (Days)",
                            min=1, max=365,
                            style={"width": 140},
                            size="sm",
                            radius="md",
                            variant="filled",
                            leftSection=DashIconify(icon="carbon:time", width=14, color="#1a73e8")
                        ),
                        dmc.MultiSelect(
                            id="select-region-config",
                            placeholder="Select Region(s)",
                            data=[
                                {"label": "United States", "value": "US"},
                                {"label": "India", "value": "IN"}
                            ],
                            value=[], 
                            hidePickedOptions=True,
                            searchable=True,
                            clearable=True,
                            style={"width": 250},
                            size="sm",
                            radius="md",
                            variant="filled",
                            leftSection=DashIconify(icon="carbon:location", width=14, color="#1a73e8"),
                            styles={
                                "input": {
                                    "backgroundColor": "#f1f3f5",
                                    "border": "none",
                                    "height": "36px",
                                    "minHeight": "36px",
                                    "overflow": "hidden"
                                },
                                "values": {
                                    "height": "100%",
                                    "alignContent": "center",
                                    "flexWrap": "nowrap",
                                    "overflowX": "auto"
                                },
                                "searchInput": { "display": "none" }
                            }
                        ),
                    ]),

                    # --- SECTION 3: ACTIONS ---
                    dmc.Group(gap="sm", align="center", children=[
                        dmc.Divider(orientation="vertical", h=32, color="gray.2"),
                        dmc.Button(
                            "Run Forecast",
                            id="run-models-btn",
                            className="gradient-button",
                            disabled=False,
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
    )