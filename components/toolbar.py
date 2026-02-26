import dash_mantine_components as dmc
from dash import html, dcc
from dash_iconify import DashIconify

def create_toolbar():
    
    # Helper for clean upload buttons
    def clean_upload_btn(label, upload_id, filename_id, icon="carbon:document-add"):
        return dmc.Box( 
            style={"position": "relative", "display": "flex", "alignItems": "center"}, 
            children=[
                 dcc.Upload(
                    id=upload_id,
                    children=dmc.Group([
                        DashIconify(icon=icon, width=16, color="var(--primary-blue)"), 
                        dmc.Text(label, fz="sm", fw=600, c="#3c4043")
                    ], gap="xs"),
                    accept=".xlsx,.xls,.csv",
                    multiple=False,
                    style={
                        "padding": "0 16px",
                        "borderRadius": "8px",
                        "border": "1px solid #dee2e6",
                        "backgroundColor": "var(--surface-bg)",
                        "cursor": "pointer",
                        "transition": "all 0.2s ease",
                        "display": "flex",
                        "alignItems": "center",
                        "height": "36px"
                    },
                ),
                dmc.Text(
                    id=filename_id, 
                    fz="10px", 
                    c="var(--primary-blue)", 
                    fw=500,
                    style={
                        "position": "absolute", 
                        "bottom": "-14px",
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
        radius=0,
        p="xs",     
        style={
            "backgroundColor": "rgba(255, 255, 255, 0.9)", 
            "backdropFilter": "blur(10px)",
            "borderBottom": "1px solid #dee2e6",
            "position": "sticky", 
            "top": "0px", 
            "zIndex": 99,
            "width": "100%",
            "height": "75px",
            "display": "flex",
            "alignItems": "center"
        },
        children=dmc.Group(
            style={"width": "100%", "padding": "0 40px"}, 
            justify="space-between",
            align="center",
            children=[
                
                # --- ALL INPUTS LEFT-ALIGNED TOGETHER ---
                dmc.Group(
                    gap="md", 
                    align="center",
                    children=[
                        # Section 1: Data Sources
                        clean_upload_btn("Upload Target (Y)", "upload-target", "filename-target", "carbon:chart-line-data"),
                        clean_upload_btn("Upload Variables (X)", "upload-features", "filename-features", "carbon:data-1"),

                        dmc.Divider(orientation="vertical", h=32, color="#dee2e6", mx="sm"),

                        # Section 2: Configuration
                        dmc.Select(
                            id="select-sheet-target",
                            placeholder="Worksheet",
                            data=[],
                            disabled=True,
                            style={"width": 160},
                            radius="md",
                            variant="filled",
                            leftSection=DashIconify(icon="carbon:table", width=14, color="var(--primary-blue)")
                        ),
                        dmc.Select(
                            id="select-col-target",
                            placeholder="Target Metric",
                            data=[],
                            disabled=True,
                            style={"width": 180},
                            radius="md",
                            variant="filled",
                            leftSection=DashIconify(icon="carbon:column", width=14, color="var(--primary-blue)")
                        ),
                        dmc.NumberInput(
                            id="forecast-horizon-input",
                            placeholder="Horizon",
                            min=1, max=365,
                            style={"width": 110},
                            radius="md",
                            variant="filled",
                            leftSection=DashIconify(icon="carbon:time", width=14, color="var(--primary-blue)")
                        ),
                        dmc.MultiSelect(
                            id="select-region-config",
                            # Initial state shows the placeholder
                            placeholder="Select Region(s)", 
                            data=[
                                {"label": "United States", "value": "US"},
                                {"label": "India", "value": "IN"}
                            ],
                            value=[], 
                            hidePickedOptions=True,
                            searchable=False,  
                            clearable=True,
                            radius="md",
                            variant="filled",
                            leftSection=DashIconify(icon="carbon:location", width=14, color="var(--primary-blue)"),
                            style={
                                "width": "auto",
                                "minWidth": "160px",
                                "maxWidth": "450px", 
                            },
                            styles={
                                "input": {
                                    "height": "36px",
                                    "minHeight": "36px",
                                    # This ensures no hidden input text interferes with visibility
                                    "textIndent": "0px", 
                                },
                                "values": {
                                    "flexWrap": "nowrap", 
                                    "overflowX": "auto",  
                                    "scrollbarWidth": "none",
                                },
                                # Specifically target the placeholder text to ensure it clears
                                "placeholder": {
                                    "display": "block", # Ensure it's visible initially
                                }
                            }
                        ),
                    ]
                ),

                # --- ACTION GROUP RIGHT-ALIGNED ---
                dmc.Button(
                    "Run Forecast",
                    id="run-models-btn",
                    leftSection=DashIconify(icon="carbon:play-filled", width=18),
                    radius="md",
                    px="xl",
                    style={
                        "background": "var(--primary-gradient)",
                        "fontWeight": 700,
                        "border": "none",
                        "color": "white",
                        "height": "42px",
                        "boxShadow": "0 4px 12px rgba(26, 115, 232, 0.3)"
                    }
                )
            ]
        )
    )