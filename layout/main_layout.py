import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

from components.header import create_header
from components.sidebar import create_sidebar
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
                "border": "1px solid #e9ecef"
            },
            children=[
                dcc.Loading(
                    children=children, 
                    type="circle", # FIXED: Changed from "custom" to "circle"
                    overlay_style={"visibility": "visible", "backgroundColor": "rgba(255,255,255,0.8)"}
                )
            ] if id_val else children
        )

def create_layout():    

    return dmc.Box(
        style={"backgroundColor": "#f8f9fa", "minHeight": "100vh"},
        children=[
            # Stores & Interval
            dcc.Store(id="log-store", data=[]),
            dcc.Store(id="graph-store", data={}),
            dcc.Store(id="predictions-store", data={}),
            
            # --- NEW STORES FOR SPLIT UPLOAD ---
            dcc.Store(id="store-target-dfs", data={}),   # Holds Target (Y) File Data
            dcc.Store(id="store-feature-dfs", data={}),  # Holds Feature (X) File Data
            
            dcc.Store(id="uploaded-raw", data=None), 
            dcc.Store(id="uploaded-dfs", data={}),   
            dcc.Store(id="uploaded-filename-store", data=None),
            
            dcc.Interval(id="log-interval", interval=1000, n_intervals=0, disabled=True),

            dcc.Download(id="download-logs"),
            dcc.Download(id="download-pred"),
            dcc.Download(id="download-csv"),

            # Header
            create_header(),

            # Main container
            dmc.Container(
                fluid=True,
                py="md",
                children=[
                    
                    # 1. TOOLBAR
                    create_toolbar(),
                    
                    dmc.Space(h="lg"),

                    # 2. Main Content Area (Full Width)
                    dmc.Paper(
                        radius="lg", shadow="md", withBorder=True, p=0,
                        style={"minHeight": "85vh", "backgroundColor": "white", "overflow": "hidden"},
                        children=[
                            dmc.Tabs(
                                id="content-tabs",
                                value="kyd", 
                                color="indigo",
                                variant="pills",
                                children=[
                                    
                                    # --- MAIN TABS LIST ---
                                    dmc.TabsList(
                                        p="sm",
                                        style={"borderBottom": "1px solid #f1f3f5", "backgroundColor": "#ffffff"},
                                        children=[
                                            dmc.TabsTab("Know Your Data", value="kyd", leftSection=DashIconify(icon="carbon:data-view-alt", width=18)),
                                            dmc.TabsTab("Execution Console", value="console", leftSection=DashIconify(icon="carbon:terminal", width=18)),
                                            dmc.TabsTab("Forecast", value="graphs", id="tab-graphs", disabled=True, leftSection=DashIconify(icon="carbon:chart-line", width=18)),
                                            dmc.TabsTab("Artifacts", value="artifacts", id="tab-artifacts", disabled=True, leftSection=DashIconify(icon="carbon:chart-relationship", width=18)),
                                        ]
                                    ),

                                    # --- TAB 1: KNOW YOUR DATA (DIAGNOSIS) ---
                                    dmc.TabsPanel(
                                        value="kyd",
                                        children=[
                                            dmc.Stack(
                                                p="xl", gap="xl",
                                                children=[
                                                    # 1. Top Control Bar
                                                    dmc.Group(
                                                        justify="space-between",
                                                        children=[
                                                            dmc.Stack(gap=0, children=[
                                                                dmc.Text("Data Diagnosis & Health Check", size="xl", fw=800, style={"color": "#1c1e21"}),
                                                                dmc.Text("Uncover insights regarding stationarity, collinearity, and seasonality.", size="sm", c="dimmed"),
                                                            ]),
                                                            dmc.Button(
                                                                "Generate Analysis",
                                                                id="btn-check-health",
                                                                size="md",
                                                                radius="md",
                                                                leftSection=DashIconify(icon="carbon:chart-evaluation", width=20)
                                                            ),
                                                        ]
                                                    ),
                                                    
                                                    dmc.Divider(),

                                                    # 2. LANDING PAGE / EMPTY STATE
                                                    dmc.Stack(
                                                        id="kyd-empty-state",
                                                        align="center",
                                                        justify="center",
                                                        style={"height": "55vh", "display": "flex", "borderRadius": "20px"},
                                                        gap="xl",
                                                        children=[
                                                            html.Div(
                                                                style={
                                                                    "background": "linear-gradient(135deg, #e3f2fd 0%, #f3e5f5 100%)",
                                                                    "padding": "40px",
                                                                    "borderRadius": "50%",
                                                                },
                                                                children=DashIconify(icon="carbon:analytics", width=100, color="#1a73e8")
                                                            ),
                                                            dmc.Stack(gap=5, align="center", children=[
                                                                dmc.Text("Intelligent Data Discovery", size="28px", fw=800, className="gradient-text"),
                                                                dmc.Text(
                                                                    "Upload your Target (Y) and Features (X) files, then click 'Generate Analysis' to unlock insights.",
                                                                    size="md", c="dimmed", style={"textAlign": "center", "maxWidth": "500px"}
                                                                ),
                                                            ]),
                                                            dmc.Group([
                                                                dmc.Badge("Stationarity", color="blue", variant="dot"),
                                                                dmc.Badge("Collinearity", color="indigo", variant="dot"),
                                                                dmc.Badge("Holiday Impact", color="cyan", variant="dot"),
                                                            ])
                                                        ]
                                                    ),

                                                    # 3. MAIN CONTENT (Hidden Initially)
                                                    html.Div(
                                                        id="kyd-main-content",
                                                        style={"display": "none"},
                                                        children=[
                                                            dmc.Tabs(
                                                                color="indigo",
                                                                variant="outline",
                                                                radius="md",
                                                                value="tab-x",
                                                                children=[
                                                                    dmc.TabsList([
                                                                        dmc.TabsTab("Features Analysis (X)", value="tab-x", leftSection=DashIconify(icon="carbon:data-1", width=16)),
                                                                        dmc.TabsTab("Target Analysis (Y)", value="tab-y", leftSection=DashIconify(icon="carbon:chart-line-data", width=16)),
                                                                    ]),

                                                                    # --- X-TAB CONTENT ---
                                                                    dmc.TabsPanel(
                                                                        value="tab-x",
                                                                        pt="lg",
                                                                        children=[
                                                                            dmc.Tabs(
                                                                                value="x-holiday",
                                                                                variant="pills",
                                                                                color="blue",
                                                                                children=[
                                                                                    dmc.TabsList([
                                                                                        dmc.TabsTab("Holiday Analysis", value="x-holiday", leftSection=DashIconify(icon="carbon:event", width=16)),
                                                                                        dmc.TabsTab("Data Statistics", value="x-health", leftSection=DashIconify(icon="carbon:report-data", width=16)),
                                                                                        dmc.TabsTab("Collinearity", value="x-collinear", leftSection=DashIconify(icon="carbon:heat-map", width=16)),
                                                                                        dmc.TabsTab("X Distribution", value="x-dist", leftSection=DashIconify(icon="carbon:histogram", width=16)),
                                                                                    ]),
                                                                                    dmc.Space(h="md"),
                                                                                    
                                                                                    dmc.TabsPanel(
                                                                                        value="x-holiday", 
                                                                                        children=[
                                                                                            elevated_card(
                                                                                                id_val="kyd-holiday-container", 
                                                                                                children=html.Div(id="kyd-holiday-container"), # Ensure ID is present
                                                                                                height="auto", 
                                                                                                overflow="visible" # Fix for rendering issues
                                                                                            )
                                                                                        ]
                                                                                    ),
                                                                                    dmc.TabsPanel(value="x-health", children=[
                                                                                        elevated_card(
                                                                                            children=html.Div(id="health-check-content"), # ID restored here
                                                                                            height="450px"
                                                                                        )
                                                                                    ]),
                                                                                    dmc.TabsPanel(value="x-collinear", children=[elevated_card(children=dcc.Graph(id="kyd-features-graph", responsive=True, style={"height": "100%"}))]),
                                                                                    dmc.TabsPanel(value="x-dist", children=[
                                                                                        dmc.Group(justify="flex-end", mb="xs", children=[dmc.RadioGroup(id="kyd-x-plot-type", value="histogram", size="sm", children=dmc.Group(gap="md", children=[dmc.Radio(label="Histogram", value="histogram"), dmc.Radio(label="Box Plot", value="boxplot"), dmc.Radio(label="Scatter Plot", value="scatterplot")]))]),
                                                                                        elevated_card(children=dcc.Graph(id="kyd-x-distribution-graph", responsive=True, style={"height": "100%"}))
                                                                                    ]),
                                                                                ]
                                                                            )
                                                                        ]
                                                                    ),

                                                                    # --- Y-TAB CONTENT ---
                                                                    dmc.TabsPanel(
                                                                        value="tab-y",
                                                                        pt="lg",
                                                                        children=[
                                                                            dmc.Tabs(
                                                                                value="y-stat",
                                                                                variant="pills",
                                                                                color="orange",
                                                                                children=[
                                                                                    dmc.TabsList([
                                                                                        dmc.TabsTab("Stationarity", value="y-stat"),
                                                                                        dmc.TabsTab("Decomposition", value="y-decomp"),
                                                                                        dmc.TabsTab("Lag Analysis", value="y-acf"),
                                                                                        dmc.TabsTab("Y Distribution", value="y-dist"),
                                                                                    ]),
                                                                                    dmc.Space(h="md"),
                                                                                    dmc.TabsPanel(value="y-stat", children=[elevated_card(children=dcc.Graph(id="kyd-stationarity-graph", responsive=True, style={"height": "100%"}))]),
                                                                                    dmc.TabsPanel(value="y-decomp", children=[elevated_card(children=dcc.Graph(id="kyd-decomposition-graph", responsive=True, style={"minHeight": "800px"}), overflow="auto")]),
                                                                                    dmc.TabsPanel(value="y-acf", children=[elevated_card(children=dcc.Graph(id="kyd-acf-pacf-graph", responsive=True, style={"height": "100%"}))]),
                                                                                    dmc.TabsPanel(value="y-dist", children=[
                                                                                        dmc.Group(justify="flex-end", mb="xs", children=[dmc.RadioGroup(id="kyd-y-plot-type", value="histogram", size="sm", children=dmc.Group(gap="md", children=[dmc.Radio(label="Histogram", value="histogram"), dmc.Radio(label="Box Plot", value="boxplot"), dmc.Radio(label="Scatter Plot", value="scatterplot")]))]),
                                                                                        elevated_card(children=dcc.Graph(id="kyd-y-distribution-graph", responsive=True, style={"height": "100%"}))
                                                                                    ]),
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

                                    # --- TAB 2: EXECUTION CONSOLE (MODERNIZED) ---
                                    dmc.TabsPanel(
                                        value="console",
                                        children=[
                                            dmc.Stack(
                                                gap="sm", p="xl", style={"height": "80vh"},
                                                children=[
                                                    # Header Section: Status and Steps side-by-side
                                                    dmc.Group(
                                                        justify="space-between", align="center",
                                                        children=[
                                                            dmc.Group(
                                                                align="center", gap="md",
                                                                children=[
                                                                    dmc.Text("Execution Status", fw=700, size="md", style={"color": "#1c1e21"}),
                                                                    dmc.Group(
                                                                        gap="sm", 
                                                                        align="center",
                                                                        children=[
                                                                            dmc.Progress(
                                                                                id="processing-progress", 
                                                                                value=0, 
                                                                                size="sm", 
                                                                                color="indigo", 
                                                                                style={"width": 260, "transition": "width 0.5s ease"}
                                                                            ),
                                                                            # Progress text moved beside the bar
                                                                            dmc.Text(id="progress-text", size="xs", fw=500, c="dimmed"),
                                                                        ]
                                                                    ),
                                                                ],
                                                            ),
                                                            dmc.Group(
                                                                gap="xs",
                                                                children=[
                                                                    dmc.Button(
                                                                        "Download Logs", 
                                                                        id="btn-download-log", 
                                                                        variant="light",
                                                                        color="gray",
                                                                        size="xs", 
                                                                        radius="md",
                                                                        leftSection=DashIconify(icon="carbon:download", width=14)
                                                                    ),
                                                                    dmc.ActionIcon(
                                                                        id="btn-stop", 
                                                                        variant="filled", 
                                                                        color="red", 
                                                                        size="lg", 
                                                                        radius="md",
                                                                        style={"boxShadow": "0 4px 12px rgba(255, 77, 79, 0.2)"},
                                                                        children=DashIconify(icon="carbon:stop-filled", width=16)
                                                                    ),
                                                                    dmc.ActionIcon(
                                                                        id="btn-restart", 
                                                                        variant="filled", 
                                                                        color="orange", 
                                                                        size="lg", 
                                                                        radius="md",
                                                                        style={"boxShadow": "0 4px 12px rgba(255, 169, 64, 0.2)"},
                                                                        children=DashIconify(icon="carbon:restart", width=16)
                                                                    ),
                                                                ],
                                                            ),
                                                        ],
                                                    ),
                                                    
                                                    # Terminal Surface
                                                    dmc.Paper(
                                                        id="console-output", 
                                                        radius="md", 
                                                        p="sm", 
                                                        withBorder=True,
                                                        style={
                                                            "height": "calc(100% - 56px)", 
                                                            "backgroundColor": "#111214", 
                                                            "color": "#e6eef8", 
                                                            "fontFamily": "monospace", 
                                                            "fontSize": "12px", 
                                                            "overflowY": "auto", 
                                                            "whiteSpace": "pre-wrap",
                                                            "border": "1px solid #2d2e32"
                                                        },
                                                    ),
                                                ],
                                            )
                                        ],
                                    ),

                                    # --- TAB 3: FORECAST (MODERNIZED) ---
                                    dmc.TabsPanel(
                                        value="graphs",
                                        children=[
                                            dmc.Stack(
                                                p="xl", gap="md",
                                                children=[
                                                    # Top Toolbar for Forecast Actions
                                                    dmc.Group(
                                                        justify="space-between", align="center",
                                                        children=[
                                                            dmc.Stack(gap=0, children=[
                                                                dmc.Text("Forecast Overview", fw=800, size="xl", style={"color": "#1c1e21"}),
                                                            ]),
                                                            dmc.Group(
                                                                gap="sm",
                                                                children=[
                                                                    dmc.Button(
                                                                        "Export CSV", 
                                                                        id="export-csv", 
                                                                        variant="light",
                                                                        color="indigo",
                                                                        size="sm", 
                                                                        radius="md", 
                                                                        leftSection=DashIconify(icon="carbon:download", width=16)
                                                                    ),
                                                                    dmc.Button(
                                                                        "Clear", 
                                                                        id="clear-graph", 
                                                                        variant="outline", 
                                                                        color="gray",
                                                                        size="sm", 
                                                                        radius="md", 
                                                                        leftSection=DashIconify(icon="carbon:eraser", width=16)
                                                                    ),
                                                                ],
                                                            ),
                                                        ],
                                                    ),
                                                    
                                                    dmc.Divider(variant="solid", color="#f1f3f5"),

                                                    # Main Graph Container wrapped in elevated card
                                                    elevated_card(
                                                        height="75vh",
                                                        children=[
                                                            dmc.Stack(
                                                                style={"height": "100%"},
                                                                children=[
                                                                    # This Div receives the metrics badges and Plotly graph from processing.py
                                                                    html.Div(
                                                                        id="graph-container", 
                                                                        style={"flex": 1, "width": "100%"}
                                                                    ),
                                                                    # Keep hidden logic containers for worker data
                                                                    html.Div(id="best-model-display", style={"display": "none"}),
                                                                    html.Div(id="best-model-error", style={"display": "none"}),
                                                                ]
                                                            )
                                                        ]
                                                    ),
                                                ]
                                            )
                                        ],
                                    ),

                                    # --- TAB 4: ARTIFACTS (FULL UPGRADE) ---
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
                                                        style={"backgroundColor": "#f8f9fa", "padding": "5px", "borderRadius": "8px"},
                                                        children=[
                                                            dmc.TabsTab("Data Treatment", value="treatment"),
                                                            dmc.TabsTab("Stationarity Test", value="stationarity"),
                                                            dmc.TabsTab("Seasonal Decomposition", value="decomposition"),
                                                            dmc.TabsTab("Lag Analysis", value="acf_pacf"),
                                                            dmc.TabsTab("Y Distribution", value="distribution"),
                                                            dmc.TabsTab("Feature Analysis", value="features"),
                                                            dmc.TabsTab("Experiment Details", value="experiments"),
                                                        ]
                                                    ),
                                                    
                                                    dmc.Space(h="lg"),

                                                    # 0. DATA TREATMENT
                                                    dmc.TabsPanel(
                                                        value="treatment",
                                                        children=[
                                                            elevated_card(height="auto", overflow="auto", children=[
                                                                dmc.Text("Data Treatment Analysis (Before vs After)", fw=700, size="lg", mb="sm"),
                                                                dcc.Graph(id="treatment-graph", responsive=True, style={"minHeight": "400px"}),
                                                                dmc.Grid([
                                                                    dmc.GridCol(
                                                                        children=[
                                                                            dmc.Text(id="y-treatment-title", fw=600, size="sm"),
                                                                            html.Pre(id="y-treatment-json", className="code-block")
                                                                        ], span={"base": 12, "md": 6} 
                                                                    ),
                                                                    dmc.GridCol(
                                                                        children=[
                                                                            dmc.Text("Features (X) Treatment Profiles", fw=600, size="sm"),
                                                                            html.Pre(id="x-treatment-json", className="code-block")
                                                                        ], span={"base": 12, "md": 6} 
                                                                    )
                                                                ], gutter="md", style={"marginTop": "20px"})
                                                            ])
                                                        ]
                                                    ),

                                                    # 1. DECOMPOSITION
                                                    dmc.TabsPanel(value="decomposition", children=[elevated_card(children=dcc.Graph(id="decomposition-graph", responsive=True, style={"width": "100%", "minHeight": "800px"}), overflow="auto")]),

                                                    # 2. STATIONARITY
                                                    dmc.TabsPanel(value="stationarity", children=[elevated_card(children=dcc.Graph(id="stationarity-graph", responsive=True, style={"height": "100%"}))]),

                                                    # 3. ACF/PACF
                                                    dmc.TabsPanel(value="acf_pacf", children=[elevated_card(children=dcc.Graph(id="acf-pacf-graph", responsive=True, style={"height": "100%"}))]),

                                                    # 4. FEATURES
                                                    dmc.TabsPanel(value="features", children=[elevated_card(children=dcc.Graph(id="features-graph", responsive=True, style={"height": "100%"}))]),

                                                    # 5. DISTRIBUTION
                                                    dmc.TabsPanel(value="distribution", children=[
                                                        dmc.Group(justify="flex-end", mb="xs", children=[dmc.RadioGroup(id="artifact-y-plot-type", value="histogram", size="sm", children=dmc.Group(gap="md", children=[dmc.Radio(label="Histogram", value="histogram"), dmc.Radio(label="Box Plot", value="boxplot"), dmc.Radio(label="Scatter Plot", value="scatterplot")]))]),
                                                        elevated_card(children=dcc.Graph(id="distribution-graph", responsive=True, style={"height": "100%"}))
                                                    ]),

                                                    # 6. EXPERIMENTS
                                                    dmc.TabsPanel(value="experiments", children=[
                                                        elevated_card(children=[
                                                            dmc.Select(id="experiment-perf-metric", label="Select Performance Metric", data=[{"label": "WMAPE", "value": "WMAPE"}, {"label": "MAE", "value": "MAE"}, {"label": "Accuracy (%)", "value": "Accuracy"}], value="WMAPE", style={"width": "250px", "marginBottom": 15}),
                                                            dcc.Graph(id="experiment-graph", responsive=True, style={"height": "100%"}) 
                                                        ])
                                                    ]),                                                                   
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