import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

from components.header import create_header
# from components.sidebar import create_sidebar
from components.toolbar import create_toolbar

def elevated_card(id_val=None, children=None, height="70vh", overflow="hidden"):
    return dmc.Card(
        withBorder=True,
        radius="lg",
        p="md",
        shadow="sm",
        style={
            "height": height, 
            "overflowY": overflow,
            "backgroundColor": "white",
            "border": "1px solid #dee2e6",
            "boxShadow": "var(--card-shadow)"  # Integrated from styles.css
        },
        children=[
            dcc.Loading(
                children=children, 
                type="circle",
                overlay_style={"visibility": "visible", "backgroundColor": "rgba(255,255,255,0.8)"}
            )
        ] if id_val else children
    )

def create_x_placeholder(text="Upload X feature file for analysis"):
    return dmc.Stack(
        align="center", justify="center",
        style={"height": "55vh", "display": "flex", "borderRadius": "20px"},
        gap="xl",
        children=[
            html.Div(
                style={"background": "var(--primary-gradient)", "padding": "40px", "borderRadius": "50%"},
                children=DashIconify(icon="carbon:document-import", width=100, color="white")
            ),
            dmc.Stack(gap=5, align="center", children=[
                dmc.Text(text, fz="28px", fw=800, className="gradient-text"),                                                                
            ]),
        ]
    )

def create_layout():    
    return dmc.Box(
        style={"backgroundColor": "var(--surface-bg)", "minHeight": "100vh"},
        children=[
            # Stores & Interval
            dcc.Store(id="log-store", data=[]),
            dcc.Store(id="graph-store", data={}),
            dcc.Store(id="predictions-store", data={}),
            dcc.Store(id="store-target-dfs", data={}),
            dcc.Store(id="store-feature-dfs", data={}),
            dcc.Store(id="selected-region-store", data=["US", "IN"]),
            dcc.Store(id="uploaded-raw", data=None), 
            dcc.Store(id="uploaded-dfs", data={}),   
            dcc.Store(id="uploaded-filename-store", data=None),
            dcc.Store(id="adjusted-forecast-store", data=None),
            dcc.Interval(id="log-interval", interval=1000, n_intervals=0, disabled=True),
            dcc.Download(id="download-logs"),
            dcc.Download(id="download-pred"),
            dcc.Download(id="download-csv"),

            # Header
            create_header(),

            # Main container
            dmc.Container(
                fluid=True,
                p=0,
                children=[
                    create_toolbar(),
                    dmc.Space(h="xs"),

                    # 2. Main Content Area
                    dmc.Box(
                        id="main-content-wrapper",
                        style={
                            "minHeight": "85vh", 
                            "backgroundColor": "white", 
                            "width": "100%",
                            "marginTop": "0px",
                            "boxShadow": "var(--card-shadow)", 
                            "borderTop": "1px solid #dee2e6"
                        },
                        children=[
                            dmc.Tabs(
                                id="content-tabs",
                                value="console", 
                                color="blue", # Match your --primary-blue
                                variant="pills", 
                                style={"padding": "15px 40px"},
                                children=[
                                    dmc.TabsList(
                                        style={
                                            "borderBottom": "2px solid #f1f3f5", # The track
                                            "backgroundColor": "transparent",
                                            "marginBottom": "20px",
                                            "gap": "10px" 
                                        },
                                        children=[
                                            dmc.TabsTab(
                                                "Execution Console", 
                                                value="console", 
                                                leftSection=DashIconify(icon="carbon:terminal", width=18),
                                            ),
                                            dmc.TabsTab(
                                                "Forecast", 
                                                value="graphs", 
                                                id="tab-graphs", 
                                                disabled=True, 
                                                leftSection=DashIconify(icon="carbon:chart-line", width=18),
                                            ),
                                            dmc.TabsTab(
                                                "Know Your Data", 
                                                value="kyd", 
                                                id="kyd-tab", 
                                                disabled=True, 
                                                leftSection=DashIconify(icon="carbon:data-view-alt", width=18),
                                            ),
                                            dmc.TabsTab(
                                                "Artifacts", 
                                                value="artifacts", 
                                                id="tab-artifacts", 
                                                disabled=True, 
                                                leftSection=DashIconify(icon="carbon:chart-relationship", width=18),
                                            ),
                                        ]
                                    ),

                                    # --- TAB: KNOW YOUR DATA (Refactored to Vertical Sidebar) ---
                                    dmc.TabsPanel(
                                        value="kyd",
                                        children=[
                                            dmc.Stack(
                                                p="xl", gap="xl",
                                                children=[
                                                    # Empty State Placeholder
                                                    dmc.Stack(
                                                        id="kyd-empty-state",
                                                        align="center", justify="center",
                                                        style={"height": "55vh", "display": "flex", "borderRadius": "20px"},
                                                        gap="xl",
                                                        children=[
                                                            html.Div(
                                                                style={"background": "var(--primary-gradient)", "padding": "40px", "borderRadius": "50%"},
                                                                children=DashIconify(icon="carbon:analytics", width=100, color="white")
                                                            ),
                                                            dmc.Text("Upload your Target (Y) and Features (X) files", fz="28px", fw=800, className="gradient-text"),
                                                        ]
                                                    ),

                                                    # Main KYD Content Canvas
                                                    html.Div(
                                                        id="kyd-main-content",
                                                        style={"display": "none"},
                                                        children=[
                                                            dmc.Tabs(
                                                                color="indigo", 
                                                                variant="default", # Standardized to Gallery Underline
                                                                radius="md", 
                                                                value="tab-x",
                                                                children=[
                                                                    dmc.TabsList(
                                                                        style={"marginBottom": "20px"}, # Added spacing for gallery feel
                                                                        children=[
                                                                            dmc.TabsTab("Features Analysis (X)", value="tab-x", leftSection=DashIconify(icon="carbon:data-1", width=16)),
                                                                            dmc.TabsTab("Target Analysis (Y)", value="tab-y", leftSection=DashIconify(icon="carbon:chart-line-data", width=16)),
                                                                        ]
                                                                    ),

                                                                    # --- SUB-TAB: Features Analysis (X) Vertical Sidebar ---
                                                                    dmc.TabsPanel(
                                                                        value="tab-x", pt="lg",
                                                                        children=[
                                                                            dmc.Tabs(
                                                                                value="x-holiday", 
                                                                                orientation="vertical", 
                                                                                color="blue", 
                                                                                variant="pills", # Standardized to Gallery Accent
                                                                                children=[
                                                                                    dmc.TabsList(
                                                                                        style={"width": "220px", "borderRight": "2px solid #f1f3f5", "paddingRight": "10px"},
                                                                                        children=[
                                                                                            dmc.TabsTab(
                                                                                                value="x-holiday",
                                                                                                children=dmc.Group([DashIconify(icon="carbon:event", width=16), "Holiday Analysis"], gap="xs")
                                                                                            ),
                                                                                            dmc.TabsTab(
                                                                                                value="x-health",
                                                                                                id="tab-x-health",
                                                                                                children=dmc.Group([DashIconify(icon="carbon:report-data", width=16), "Data Statistics"], gap="xs")
                                                                                            ),
                                                                                            dmc.TabsTab(
                                                                                                value="x-collinear",
                                                                                                id="tab-x-collinear",
                                                                                                children=dmc.Group([DashIconify(icon="carbon:heat-map", width=16), "Collinearity"], gap="xs")
                                                                                            ),
                                                                                            dmc.TabsTab(
                                                                                                value="x-dist",
                                                                                                id="tab-x-dist",
                                                                                                children=dmc.Group([DashIconify(icon="carbon:chart-histogram", width=16), "X Distribution"], gap="xs")
                                                                                            ),
                                                                                        ]
                                                                                    ),
                                                                                    # Content Canvas for X (Logic Preserved)
                                                                                    dmc.Box(pl="xl", style={"flex": 1}, children=[
                                                                                        dmc.TabsPanel(value="x-holiday", children=[elevated_card(id_val="kyd-holiday-container", children=html.Div(id="kyd-holiday-container"), height="auto", overflow="visible")]),
                                                                                        dmc.TabsPanel(value="x-health", children=[dmc.Stack(gap="xs", children=[dmc.Text("Feature Statistics (Raw Data)", fw=600, fz="sm", c="dimmed", mb="xs"), elevated_card(id_val="loading-x-health-raw", children=html.Div(id="health-check-content-raw"), height="auto")])]),
                                                                                        dmc.TabsPanel(value="x-collinear", children=[dmc.Group(justify="flex-end", mb="xs", children=[dmc.RadioGroup(id="kyd-corr-method", value="pearson", children=dmc.Group(gap="md", children=[dmc.Radio(label="Pearson", value="pearson"), dmc.Radio(label="Spearman", value="spearman")]))]), elevated_card(id_val="loading-x-collinear", height="auto", children=[dmc.Text(id="kyd-collinear-type-label", fw=700, fz="sm", c="indigo", mb="lg"), html.Div(id="kyd-features-graph", style={"width": "100%", "minHeight": "500px"})])]),
                                                                                        dmc.TabsPanel(value="x-dist", children=[dmc.Stack(gap="md", children=[dmc.Group(justify="flex-end", children=[dmc.RadioGroup(id="kyd-x-plot-type", value="histogram", children=dmc.Group(gap="md", children=[dmc.Radio(label="Histogram", value="histogram"), dmc.Radio(label="Box Plot", value="boxplot"), dmc.Radio(label="Scatter Plot", value="scatterplot")]))]), dmc.Text("Feature Distributions", fw=600, fz="sm", c="dimmed", mb="xs"), elevated_card(id_val="loading-x-dist-raw", children=html.Div(id="kyd-x-distribution-graph-raw"), height="auto", overflow="visible")])]),
                                                                                    ])
                                                                                ]
                                                                            )
                                                                        ]
                                                                    ),

                                                                    # --- SUB-TAB: Target Analysis (Y) Vertical Sidebar ---
                                                                    dmc.TabsPanel(
                                                                        value="tab-y", pt="lg",
                                                                        children=[
                                                                            dmc.Tabs(
                                                                                value="y-stat", 
                                                                                orientation="vertical", 
                                                                                color="orange", 
                                                                                variant="default", # Standardized to Gallery Accent
                                                                                children=[
                                                                                    dmc.TabsList(
                                                                                        style={"width": "200px", "borderRight": "2px solid #f1f3f5", "paddingRight": "10px"},
                                                                                        children=[
                                                                                            dmc.TabsTab("Stationarity", value="y-stat", leftSection=DashIconify(icon="carbon:analytics", width=16)),
                                                                                            dmc.TabsTab("Decomposition", value="y-decomp", leftSection=DashIconify(icon="carbon:chart-bubble-packed", width=16)),
                                                                                            dmc.TabsTab("Lag Analysis", value="y-acf", leftSection=DashIconify(icon="carbon:chart-spiral", width=16)),
                                                                                            dmc.TabsTab("Y Distribution", value="y-dist", leftSection=DashIconify(icon="carbon:chart-histogram", width=16)),
                                                                                        ]
                                                                                    ),
                                                                                    # Content Canvas for Y (Logic Preserved)
                                                                                    dmc.Box(pl="xl", style={"flex": 1}, children=[
                                                                                        dmc.TabsPanel(value="y-stat", children=[dmc.Grid(gutter="md", children=[dmc.GridCol(span=6, children=[dmc.Text("Raw Data Stationarity", fw=600, fz="sm", c="dimmed", mb="xs"), elevated_card(id_val="loading-y-stat-raw", children=[dcc.Graph(id="kyd-stationarity-graph-raw"), html.Div(id="kyd-stationarity-results-raw")], height="auto")]), dmc.GridCol(span=6, children=[dmc.Text("Processed Data Stationarity", fw=600, fz="sm", className="gradient-text", mb="xs"), elevated_card(id_val="loading-y-stat-processed", children=[dcc.Graph(id="kyd-stationarity-graph-processed"), html.Div(id="kyd-stationarity-results-processed")], height="auto")])])]),
                                                                                        dmc.TabsPanel(value="y-decomp", children=[dmc.Grid(gutter="md", children=[dmc.GridCol(span=6, children=[dmc.Text("Raw Seasonal Decomposition", fw=600, fz="sm", c="dimmed", mb="xs"), elevated_card(id_val="loading-y-decomp-raw", children=dcc.Graph(id="kyd-decomposition-graph-raw"), height="800px", overflow="auto")]), dmc.GridCol(span=6, children=[dmc.Text("Processed Seasonal Decomposition", fw=600, fz="sm", className="gradient-text", mb="xs"), elevated_card(id_val="loading-y-decomp-processed", children=dcc.Graph(id="kyd-decomposition-graph-processed"), height="800px", overflow="auto")])])]),
                                                                                        dmc.TabsPanel(value="y-acf", children=[dmc.Grid(gutter="md", children=[dmc.GridCol(span=6, children=[dmc.Text("Raw Lag Analysis (ACF/PACF)", fw=600, fz="sm", c="dimmed", mb="xs"), elevated_card(id_val="loading-y-acf-raw", children=[dcc.Graph(id="kyd-acf-pacf-graph-raw"), html.Div(id="kyd-acf-results-raw")], height="auto")]), dmc.GridCol(span=6, children=[dmc.Text("Processed Lag Analysis (ACF/PACF)", fw=600, fz="sm", className="gradient-text", mb="xs"), elevated_card(id_val="loading-y-acf-processed", children=[dcc.Graph(id="kyd-acf-pacf-graph-processed"), html.Div(id="kyd-acf-results-processed")], height="auto")])])]),
                                                                                        dmc.TabsPanel(value="y-dist", children=[dmc.Stack(gap="md", children=[dmc.Group(justify="flex-end", children=[dmc.RadioGroup(id="kyd-y-plot-type", value="histogram", children=dmc.Group(gap="md", children=[dmc.Radio(label="Histogram", value="histogram"), dmc.Radio(label="Box Plot", value="boxplot"), dmc.Radio(label="Scatter Plot", value="scatterplot")]))]), dmc.Grid(gutter="md", children=[dmc.GridCol(span=6, children=[dmc.Text("Raw Y Distribution", fw=600, fz="sm", c="dimmed", mb="xs"), elevated_card(id_val="loading-y-dist-raw", children=[html.Div(id="kyd-y-dist-results-raw"), dcc.Graph(id="kyd-y-distribution-graph-raw")], height="auto")]), dmc.GridCol(span=6, children=[dmc.Text("Processed Y Distribution", fw=600, fz="sm", className="gradient-text", mb="xs"), elevated_card(id_val="loading-y-dist-processed", children=[html.Div(id="kyd-y-dist-results-processed"), dcc.Graph(id="kyd-y-distribution-graph-processed")], height="auto")])])])]),
                                                                                    ])
                                                                                ]
                                                                            )
                                                                        ]
                                                                    ),
                                                                ]
                                                            )
                                                        ]
                                                    )
                                                ]
                                            )
                                        ]
                                    ),

                                    # --- TAB: EXECUTION CONSOLE ---
                                    dmc.TabsPanel(
                                        value="console",
                                        children=[
                                            dmc.Stack(
                                                p="xl", 
                                                style={"height": "auto", "width": "100%"}, # Ensure stack fills width
                                                children=[
                                                    # Empty State Placeholder (Logic Preserved)
                                                    dmc.Stack(
                                                        id="console-empty-state",
                                                        align="center",
                                                        justify="center",
                                                        style={"height": "55vh", "display": "flex", "borderRadius": "20px"},
                                                        gap="xl",
                                                        children=[
                                                            html.Div(
                                                                style={
                                                                    "background": "var(--primary-gradient)",
                                                                    "padding": "25px",
                                                                    "borderRadius": "50%",
                                                                    "display": "flex",
                                                                    "alignItems": "center",
                                                                    "justifyContent": "center",
                                                                    "boxShadow": "0 10px 30px -10px rgba(0,0,0,0.2)"
                                                                },
                                                                children=DashIconify(icon="carbon:terminal", width=65, color="white")
                                                            ),
                                                            dmc.Text("Upload data to Generate Forecast", fz="28px", fw=800, className="gradient-text", style={"textAlign": "center"}),
                                                        ]
                                                    ),

                                                    # Main Console Grid - Added grow=True for full-width filling
                                                    dmc.Grid(
                                                        id="console-main-content",
                                                        gutter="xl",
                                                        grow=True, # Forces columns to expand to fill empty space
                                                        style={"display": "none", "width": "100%"},
                                                        children=[
                                                            dmc.GridCol(span=8, children=[
                                                                dmc.Stack(gap="sm", style={"width": "100%"}, children=[
                                                                    
                                                                    # LINE 1: Status Title, Progress Bar, and Action Buttons
                                                                    dmc.Group(
                                                                        justify="space-between", align="center",
                                                                        children=[
                                                                            dmc.Group(
                                                                                align="center", gap="xl",
                                                                                children=[
                                                                                    dmc.Text("Execution Status", fw=700, fz="md", style={"color": "#1c1e21", "fontSize": "16px"}),
                                                                                    dmc.Progress(
                                                                                        id="processing-progress", 
                                                                                        value=0, 
                                                                                        size="sm", 
                                                                                        color="indigo", 
                                                                                        style={"width": 250, "transition": "width 0.5s ease"}
                                                                                    ),
                                                                                ]
                                                                            ),
                                                                            dmc.Group(
                                                                                gap="xs",
                                                                                children=[
                                                                                    dmc.Button("Download Logs", id="btn-download-log", variant="light", color="gray", fz="xs", radius="md", leftSection=DashIconify(icon="carbon:download", width=14)),
                                                                                    dmc.ActionIcon(id="btn-stop", variant="filled", color="red", size="lg", radius="md", children=DashIconify(icon="carbon:stop-filled", width=16)),
                                                                                    dmc.ActionIcon(id="btn-restart", variant="filled", color="orange", size="lg", radius="md", children=DashIconify(icon="carbon:restart", width=16)),
                                                                                ],
                                                                            ),
                                                                        ],
                                                                    ),
                                                                    
                                                                    # LINE 2: Dedicated row for Progress Message (_emit_status)
                                                                    dmc.Box(
                                                                        pl=3, 
                                                                        children=dmc.Text(
                                                                            id="progress-text", 
                                                                            fz="sm",      
                                                                            fw=600,      
                                                                            className="gradient-text", 
                                                                            style={"letterSpacing": "0.3px", "fontSize": "14px"}
                                                                        )
                                                                    ),

                                                                    # Output Window - Explicitly set to 100% width
                                                                    dmc.Paper(
                                                                        id="console-output", 
                                                                        radius="md", p="sm", withBorder=True,
                                                                        style={
                                                                            "height": "calc(80vh - 80px)", 
                                                                            "width": "100%",
                                                                            "backgroundColor": "#111214", "color": "#e6eef8", 
                                                                            "fontFamily": "monospace", "fontSize": "14px", 
                                                                            "overflowY": "auto", "whiteSpace": "pre-wrap",
                                                                            "border": "1px solid #2d2e32"
                                                                        },
                                                                    ),
                                                                ])
                                                            ]),

                                                            # Configuration Side-Card - Explicitly set to 100% width
                                                            dmc.GridCol(span=4, children=[
                                                                dmc.Paper(
                                                                    withBorder=True, 
                                                                    radius="md", 
                                                                    p="xl",
                                                                    style={
                                                                        "height": "100%", 
                                                                        "width": "100%",
                                                                        "backgroundColor": "white",
                                                                        "boxShadow": "var(--card-shadow)",
                                                                        "border": "1px solid #dee2e6"
                                                                    },
                                                                    children=[
                                                                        dmc.Stack(gap="lg", children=[
                                                                            dmc.Group(gap="sm", children=[
                                                                                DashIconify(icon="carbon:settings-adjust", width=24, color="var(--primary-blue)"),
                                                                                dmc.Text("Configuration", fw=700, fz="lg", className="gradient-text"),
                                                                            ]),
                                                                            dmc.Divider(variant="solid", color="#f1f3f5"),
                                                                            
                                                                            dmc.Select(
                                                                                id="test-window-select",
                                                                                label="Test Window Size (Days)",
                                                                                data=[
                                                                                    {"label": "30 Days", "value": "30"}, 
                                                                                    {"label": "60 Days", "value": "60"}, 
                                                                                    {"label": "90 Days", "value": "90"}, 
                                                                                    {"label": "120 Days", "value": "120"}
                                                                                ],
                                                                                value="30",
                                                                                radius="md",
                                                                                variant="filled",
                                                                                leftSection=DashIconify(icon="carbon:time", color="var(--primary-blue)"),
                                                                                style={"width": "100%"},
                                                                                styles={"input": {"backgroundColor": "#f1f3f5", "border": "none"}}
                                                                            ),
                                                                        ])
                                                                    ]
                                                                )
                                                            ])
                                                        ]
                                                    )
                                                ]
                                            )
                                        ],
                                    ),

                                    # --- TAB: FORECAST ---
                                    dmc.TabsPanel(
                                        value="graphs",
                                        children=[
                                            dmc.Grid(
                                                p="xl", gutter="xl",
                                                children=[
                                                    # Main Graph Area
                                                    dmc.GridCol(
                                                        span=8,
                                                        children=[
                                                            elevated_card(
                                                                height="100%",
                                                                children=[
                                                                    dmc.Stack(
                                                                        style={"height": "100%", "display": "flex", "flexDirection": "column"}, 
                                                                        gap="md",
                                                                        children=[
                                                                            dmc.Group(
                                                                                justify="space-between", align="center", p="sm",
                                                                                children=[
                                                                                    html.Div(id="best-model-display", style={"display": "flex", "alignItems": "center", "gap": "10px"}),
                                                                                    dmc.Group(
                                                                                        gap="sm",
                                                                                        children=[
                                                                                            dmc.Button("Export CSV", id="export-csv", variant="light", color="indigo", fz="sm", radius="md", leftSection=DashIconify(icon="carbon:download", width=16)),
                                                                                            dmc.Button("Clear", id="clear-graph", variant="outline", color="gray", fz="sm", radius="md", leftSection=DashIconify(icon="carbon:eraser", width=16)),
                                                                                        ],
                                                                                    ),
                                                                                ],
                                                                            ),
                                                                            dmc.Divider(variant="solid", color="#f1f3f5", px="sm"),
                                                                            html.Div(id="graph-container", style={"flex": "1", "width": "100%", "minHeight": "0", "paddingBottom": "10px"}),
                                                                        ]
                                                                    )
                                                                ]
                                                            ),
                                                        ]
                                                    ),
                                                    # NEW: LLM Chatbot Sidebar
                                                    dmc.GridCol(
                                                        span=4,
                                                        children=[
                                                            elevated_card(
                                                                height="100%",
                                                                children=[
                                                                    dmc.Stack(
                                                                        gap="lg",
                                                                        children=[
                                                                            dmc.Group(gap="sm", children=[
                                                                                DashIconify(icon="carbon:bot", width=24, color="var(--primary-blue)"),
                                                                                dmc.Text("Forecast Assistant", fw=700, fz="lg", className="gradient-text"),
                                                                            ]),
                                                                            dmc.Divider(color="#f1f3f5"),
                                                                            # Chat Display Area
                                                                            dmc.ScrollArea(
                                                                                h=400, offsetScrollbars=True,
                                                                                children=html.Div(id="chat-history", children=[
                                                                                    dmc.Alert(
                                                                                        "I can apply business constraints on your forecast data ! Feel free to ask any business rules to apply",
                                                                                        title="Ready to Assist", color="indigo", variant="light", radius="md"
                                                                                    )
                                                                                ])
                                                                            ),
                                                                            # Input Area
                                                                            dmc.Textarea(
                                                                                id="llm-constraint-input",
                                                                                placeholder="Enter business constraints in plain English...",
                                                                                minRows=3, radius="md", variant="filled",
                                                                                styles={"input": {"backgroundColor": "#f1f3f5", "border": "none"}}
                                                                            ),
                                                                            dmc.Button(
                                                                                "Apply Constraints", id="apply-llm-btn",
                                                                                fullWidth=True, radius="md",
                                                                                leftSection=DashIconify(icon="carbon:send-alt-filled"),
                                                                                style={"background": "var(--primary-gradient)", "fontWeight": 700}
                                                                            ),
                                                                            dmc.Button(
                                                                                "Reset Forecast", id="reset-llm-btn",
                                                                                variant="outline", color="gray", fullWidth=True, radius="md"
                                                                            )
                                                                        ]
                                                                    )
                                                                ]
                                                            )
                                                        ]
                                                    )
                                                ]
                                            )
                                        ]
                                    ),

                                    # --- TAB: ARTIFACTS ---
                                    dmc.TabsPanel(
                                        value="artifacts",
                                        children=[
                                            dmc.Tabs(
                                                value="treatment", 
                                                variant="outline",
                                                color="indigo",
                                                p="md",
                                                children=[
                                                    dmc.TabsList(
                                                        style={"backgroundColor": "var(--surface-bg)", "padding": "5px", "borderRadius": "8px"},
                                                        children=[
                                                            dmc.TabsTab("Data Treatment", value="treatment"),
                                                            dmc.TabsTab("Feature Analysis", value="features"),
                                                            dmc.TabsTab("Experiment Details", value="experiments"),
                                                        ]
                                                    ),
                                                    dmc.Space(h="lg"),
                                                    dmc.TabsPanel(value="treatment", children=[elevated_card(height="auto", children=[dcc.Graph(id="treatment-graph", responsive=True), dmc.Grid([dmc.GridCol(children=[dmc.Text(id="y-treatment-title", fw=600, fz="sm"), html.Pre(id="y-treatment-json", className="code-block")], span={"base": 12, "md": 6}), dmc.GridCol(children=[dmc.Text("Features (X) Treatment Profiles", fw=600, fz="sm"), html.Pre(id="x-treatment-json", className="code-block")], span={"base": 12, "md": 6})], gutter="md")])]),
                                                    dmc.TabsPanel(value="features", children=[dmc.Group(justify="flex-end", mb="xs", children=[dmc.RadioGroup(id="artifact-corr-method", value="pearson", children=dmc.Group(gap="md", children=[dmc.Radio(label="Pearson", value="pearson"), dmc.Radio(label="Spearman", value="spearman")]))]), elevated_card(children=dcc.Graph(id="features-graph", responsive=True))]),
                                                    dmc.TabsPanel(
                                                        value="experiments",
                                                        children=[
                                                            elevated_card(
                                                                height="auto",
                                                                children=[
                                                                    dmc.Stack(
                                                                        gap="md",
                                                                        children=[
                                                                            dmc.Group(
                                                                                justify="space-between",
                                                                                children=[
                                                                                    dmc.Stack(gap=4, children=[dmc.Text("Model Performance Benchmark", fw=700, fz="lg", style={"color": "#1c1e21"}), dmc.Group(id="experiment-split-info", gap="xs")]),
                                                                                    dmc.Select(id="experiment-perf-metric", placeholder="Select Metric", data=[{"label": "WMAPE", "value": "WMAPE"}, {"label": "MAE", "value": "MAE"}, {"label": "Accuracy (%)", "value": "Accuracy"}], value="WMAPE", style={"width": "200px"}, fz="sm", radius="md", variant="filled", leftSection=DashIconify(icon="carbon:meter-alt", width=16, color="var(--primary-blue)"))
                                                                                ]
                                                                            ),
                                                                            dmc.Divider(color="#f1f3f5"),
                                                                            dmc.Box(style={"minHeight": "500px", "width": "100%"}, children=dcc.Graph(id="experiment-graph", responsive=True, style={"height": "100%"}, config={'displayModeBar': False}))
                                                                        ]
                                                                    )
                                                                ]
                                                            )
                                                        ]
                                                    ),                                                                  
                                                ]
                                            )
                                        ]
                                    ),
                                ],
                            )
                        ],
                    )
                ],
            ),
        ],
    )