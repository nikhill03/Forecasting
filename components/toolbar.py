import dash_mantine_components as dmc
from dash import html, dcc
from dash_iconify import DashIconify

def create_toolbar():
    
    # helper for clean upload buttons (Google Ads style "Add" chips)
    def clean_upload_btn(label, upload_id, filename_id, icon="carbon:document-add"):
        return dmc.Stack(gap=0, children=[
             dcc.Upload(
                id=upload_id,
                children=dmc.Group([
                    DashIconify(icon=icon, width=16, color="#1a73e8"), # Google Blue
                    dmc.Text(label, size="sm", fw=500, c="#3c4043")
                ], gap="xs"),
                accept=".xlsx,.xls,.csv",
                multiple=False,
                style={
                    "padding": "6px 12px",
                    "borderRadius": "4px",
                    "border": "1px solid #dadce0",
                    "backgroundColor": "white",
                    "cursor": "pointer",
                    "transition": "all 0.2s ease",
                    "display": "flex",
                    "alignItems": "center"
                },
                # Hover effect handling would typically be CSS, but this is clean enough
            ),
            dmc.Text(id=filename_id, size="10px", c="dimmed", style={"maxWidth": "120px", "whiteSpace": "nowrap", "overflow": "hidden", "textOverflow": "ellipsis", "marginTop": "2px", "paddingLeft": "4px"})
        ])

    return dmc.Paper(
        shadow="none", # Flat look
        radius=0,
        p="sm",
        style={
            "backgroundColor": "white", 
            "borderBottom": "1px solid #dadce0", # Google-like subtle border
            "position": "sticky", 
            "top": 0, 
            "zIndex": 99
        },
        children=dmc.Group(
            justify="space-between",
            align="center", # Vertically center everything
            children=[
                
                # --- SECTION 1: DATA SOURCES ---
                dmc.Group(gap="md", children=[
                    dmc.Text("Data Sources", size="xs", fw=700, c="dimmed", tt="uppercase", style={"letterSpacing": "0.5px"}),
                    clean_upload_btn("Target (Y)", "upload-target", "filename-target", "carbon:chart-line-data"),
                    clean_upload_btn("Features (X)", "upload-features", "filename-features", "carbon:data-1"),
                ]),

                # Divider
                dmc.Divider(orientation="vertical", h=32, color="gray.3"),

                # --- SECTION 2: CONFIGURATION ---
                dmc.Group(gap="sm", children=[
                    dmc.Select(
                        id="select-sheet-target",
                        placeholder="Sheet",
                        data=[],
                        disabled=True,
                        style={"width": 130},
                        size="sm",
                        radius="sm",
                        variant="filled", # Gray background input
                        leftSection=DashIconify(icon="carbon:table", width=14, color="#5f6368")
                    ),
                    dmc.Select(
                        id="select-col-target",
                        placeholder="Column",
                        data=[],
                        disabled=True,
                        style={"width": 130},
                        size="sm",
                        radius="sm",
                        variant="filled",
                        leftSection=DashIconify(icon="carbon:column", width=14, color="#5f6368")
                    ),
                    dmc.NumberInput(
                        id="forecast-horizon-input",
                        value=60,
                        min=1, max=365, step=1,
                        placeholder="60",
                        style={"width": 80},
                        size="sm",
                        radius="sm",
                        variant="filled",
                        leftSection=DashIconify(icon="carbon:time", width=14, color="#5f6368")
                    ),
                ]),

                # Divider
                dmc.Divider(orientation="vertical", h=32, color="gray.3"),

                # --- SECTION 3: ACTIONS ---
                dmc.Group(gap="xs", children=[
                    # Primary Action (Run)
                    dmc.Button(
                        "Run Forecast",
                        id="run-models-btn",
                        color="blue", # Google Blue
                        leftSection=DashIconify(icon="carbon:play-filled"),
                        size="sm",
                        radius="sm"
                    ),
                    
                    # Icon Actions Group
                    dmc.Group(gap=4, children=[
                        dmc.Tooltip(
                            label="Stop",
                            children=dmc.ActionIcon(
                                id="btn-stop", variant="light", color="red", size="lg", radius="sm",
                                children=DashIconify(icon="carbon:stop-filled", width=18)
                            )
                        ),
                        dmc.Tooltip(
                            label="Restart",
                            children=dmc.ActionIcon(
                                id="btn-restart", variant="light", color="orange", size="lg", radius="sm",
                                children=DashIconify(icon="carbon:restart", width=18)
                            )
                        ),
                        dmc.Tooltip(
                            label="Clear",
                            children=dmc.ActionIcon(
                                id="clear-graph", variant="subtle", color="gray", size="lg", radius="sm",
                                children=DashIconify(icon="carbon:trash-can", width=18)
                            )
                        ),
                    ])
                ])
            ]
        )
    )