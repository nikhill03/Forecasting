import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

from components.header import create_header
from components.sidebar import create_sidebar


def create_layout():

    return dmc.Box(
        style={"backgroundColor": "#f6f7fb", "minHeight": "100vh"},
        children=[
            # Stores & Interval
            dcc.Store(id="log-store", data=[]),
            dcc.Store(id="graph-store", data={}),
            dcc.Store(id="predictions-store", data={}),
            
            # --- NEW STORES FOR SPLIT UPLOAD ---
            dcc.Store(id="store-target-dfs", data={}),   # Holds Target (Y) File Data
            dcc.Store(id="store-feature-dfs", data={}),  # Holds Feature (X) File Data
            
            dcc.Store(id="uploaded-raw", data=None), # Keep for backward compatibility/logging
            dcc.Store(id="uploaded-dfs", data={}),   # Keep for backward compatibility/logging
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
                    dmc.Grid(
                        gutter="md",
                        children=[
                            # Sidebar
                            dmc.GridCol(
                                span={"base": 12, "sm": 4, "lg": 3},
                                children=[create_sidebar()],
                            ),

                            # Main Content
                            dmc.GridCol(
                                span={"base": 12, "sm": 8, "lg": 9},
                                children=[
                                    dmc.Paper(
                                        radius="md", shadow="sm", withBorder=True, p=0,
                                        style={"minHeight": "85vh", "backgroundColor": "white", "overflow": "hidden"},
                                        children=[
                                            dmc.Tabs(
                                                id="content-tabs",
                                                value="kyd",  # Default to Know Your Data
                                                color="cyan",
                                                variant="pills",
                                                children=[
                                                    
                                                    # --- TABS LIST ---
                                                    dmc.TabsList(
                                                        children=[
                                                            # 1. NEW: Know Your Data
                                                            dmc.TabsTab(
                                                                "Know Your Data",
                                                                value="kyd",
                                                                leftSection=DashIconify(icon="carbon:data-view-alt", width=16),
                                                            ),
                                                            # 2. Execution Console
                                                            dmc.TabsTab(
                                                                "Execution Console",
                                                                value="console",
                                                                leftSection=DashIconify(icon="carbon:terminal", width=16),
                                                            ),
                                                            # 3. Forecast
                                                            dmc.TabsTab(
                                                                "Forecast",
                                                                value="graphs",
                                                                id="tab-graphs",
                                                                disabled=True,
                                                                leftSection=DashIconify(icon="carbon:chart-line", width=16),
                                                            ),
                                                            # 4. Artifacts
                                                            dmc.TabsTab(
                                                                "Artifacts",
                                                                value="artifacts",
                                                                id="tab-artifacts",
                                                                disabled=True,
                                                                leftSection=DashIconify(icon="carbon:chart-relationship", width=16),
                                                            ),
                                                        ]
                                                    ),

                                                    # --- TAB 1: KNOW YOUR DATA (UPDATED) ---
                                                    dmc.TabsPanel(
                                                        value="kyd",
                                                        children=[
                                                            dmc.Stack(
                                                                p="lg",
                                                                gap="md",
                                                                children=[
                                                                    # 1. Top Control Bar
                                                                    dmc.Group(
                                                                        justify="space-between",
                                                                        children=[
                                                                            dmc.Text("Data Diagnosis & Health Check", size="lg", fw=500, c="dimmed"),
                                                                            dmc.Button(
                                                                                "Generate Analysis",
                                                                                id="btn-check-health",
                                                                                size="md",
                                                                                color="teal",
                                                                                variant="filled",
                                                                                leftSection=DashIconify(icon="carbon:chart-evaluation", width=20)
                                                                            ),
                                                                        ]
                                                                    ),
                                                                    
                                                                    dmc.Divider(),

                                                                    # 2. Main Tabs: Features (X) vs Target (Y)
                                                                    dmc.Tabs(
                                                                        color="teal",
                                                                        variant="outline",
                                                                        radius="sm",
                                                                        value="tab-x",  # Default to X analysis
                                                                        children=[
                                                                            dmc.TabsList([
                                                                                dmc.TabsTab("1. Features Analysis (X)", value="tab-x", leftSection=DashIconify(icon="carbon:data-1", width=16)),
                                                                                dmc.TabsTab("2. Target Analysis (Y)", value="tab-y", leftSection=DashIconify(icon="carbon:chart-line-data", width=16)),
                                                                            ]),

                                                                            # ------------------------------------------------
                                                                            # X-TAB CONTENT (Features)
                                                                            # ------------------------------------------------
                                                                            dmc.TabsPanel(
                                                                                value="tab-x",
                                                                                pt="md",
                                                                                children=[
                                                                                    dmc.Tabs(
                                                                                        value="x-health",
                                                                                        variant="pills",
                                                                                        color="indigo",
                                                                                        children=[
                                                                                            dmc.TabsList([
                                                                                                dmc.TabsTab("Health Summary", value="x-health", leftSection=DashIconify(icon="carbon:report-data", width=16)),
                                                                                                dmc.TabsTab("Collinearity (Heatmap)", value="x-collinear", leftSection=DashIconify(icon="carbon:heat-map", width=16)),
                                                                                                dmc.TabsTab("Distributions", value="x-dist", leftSection=DashIconify(icon="carbon:histogram", width=16)),
                                                                                            ]),
                                                                                            dmc.Space(h=15),
                                                                                            
                                                                                            # Sub-Tab: Health Table
                                                                                            dmc.TabsPanel(
                                                                                                value="x-health",
                                                                                                children=[
                                                                                                    dcc.Loading(
                                                                                                        id="load-health",
                                                                                                        children=html.Div(id="health-check-content", style={"minHeight": "400px"})
                                                                                                    )
                                                                                                ]
                                                                                            ),
                                                                                            
                                                                                            # Sub-Tab: Collinearity
                                                                                            dmc.TabsPanel(
                                                                                                value="x-collinear",
                                                                                                children=[
                                                                                                    dmc.Card(withBorder=True, radius="md", p="md", children=[
                                                                                                        dcc.Graph(id="kyd-features-graph", style={"height": "75vh"})
                                                                                                    ])
                                                                                                ]
                                                                                            ),
                                                                                            
                                                                                            # Sub-Tab: X Distributions
                                                                                            dmc.TabsPanel(
                                                                                                value="x-dist",
                                                                                                children=[
                                                                                                    dmc.Card(withBorder=True, radius="md", p="md", children=[
                                                                                                        dcc.Graph(id="kyd-x-distribution-graph", style={"height": "60vh"})
                                                                                                    ])
                                                                                                ]
                                                                                            ),
                                                                                        ]
                                                                                    )
                                                                                ]
                                                                            ),

                                                                            # ------------------------------------------------
                                                                            # Y-TAB CONTENT (Target)
                                                                            # ------------------------------------------------
                                                                            dmc.TabsPanel(
                                                                                value="tab-y",
                                                                                pt="md",
                                                                                children=[
                                                                                    dmc.Tabs(
                                                                                        value="y-stat",
                                                                                        variant="pills",
                                                                                        color="orange",
                                                                                        children=[
                                                                                            dmc.TabsList([
                                                                                                dmc.TabsTab("Stationarity", value="y-stat"),
                                                                                                dmc.TabsTab("Decomposition", value="y-decomp"),
                                                                                                dmc.TabsTab("Autocorrelation", value="y-acf"),
                                                                                                dmc.TabsTab("Distribution", value="y-dist"),
                                                                                            ]),
                                                                                            dmc.Space(h=15),

                                                                                            # Sub-Tab: Stationarity
                                                                                            dmc.TabsPanel(
                                                                                                value="y-stat",
                                                                                                children=[
                                                                                                    dmc.Card(withBorder=True, radius="md", p="md", children=[
                                                                                                        dcc.Graph(id="kyd-stationarity-graph", style={"height": "60vh"})
                                                                                                    ])
                                                                                                ]
                                                                                            ),
                                                                                            
                                                                                            # Sub-Tab: Decomposition
                                                                                            dmc.TabsPanel(
                                                                                                value="y-decomp",
                                                                                                children=[
                                                                                                    dmc.Card(withBorder=True, radius="md", p="md", children=[
                                                                                                        dcc.Graph(id="kyd-decomposition-graph", style={"height": "80vh"})
                                                                                                    ])
                                                                                                ]
                                                                                            ),

                                                                                            # Sub-Tab: ACF/PACF
                                                                                            dmc.TabsPanel(
                                                                                                value="y-acf",
                                                                                                children=[
                                                                                                    dmc.Card(withBorder=True, radius="md", p="md", children=[
                                                                                                        dcc.Graph(id="kyd-acf-pacf-graph", style={"height": "80vh"})
                                                                                                    ])
                                                                                                ]
                                                                                            ),
                                                                                            
                                                                                            # Sub-Tab: Y Distribution
                                                                                            dmc.TabsPanel(
                                                                                                value="y-dist",
                                                                                                children=[
                                                                                                    dmc.Card(withBorder=True, radius="md", p="md", children=[
                                                                                                        dcc.Graph(id="kyd-y-distribution-graph", style={"height": "60vh"})
                                                                                                    ])
                                                                                                ]
                                                                                            ),
                                                                                        ]
                                                                                    )
                                                                                ]
                                                                            ),
                                                                        ]
                                                                    )
                                                                ]
                                                            )
                                                        ]
                                                    ),

                                                    # --- TAB 2: EXECUTION CONSOLE ---
                                                    dmc.TabsPanel(
                                                        value="console",
                                                        children=[
                                                            dmc.Stack(
                                                                gap="sm", p="md", style={"height": "80vh"},
                                                                children=[
                                                                    dmc.Group(
                                                                        justify="space-between", align="center",
                                                                        children=[
                                                                            dmc.Group(
                                                                                align="center", gap="sm",
                                                                                children=[
                                                                                    dmc.Text("Execution Status", fw=700, size="md"),
                                                                                    dmc.Progress(id="processing-progress", value=0, size="sm", style={"width": 260}),
                                                                                    dmc.Text(id="progress-text", size="xs", c="dimmed"),
                                                                                ],
                                                                            ),
                                                                            dmc.Group(
                                                                                gap="xs",
                                                                                children=[
                                                                                    dmc.Text(id="current-metric", size="sm", fw=700),
                                                                                    dmc.Button("Download Logs", id="btn-download-log", size="xs", leftSection=DashIconify(icon="carbon:download", width=14)),
                                                                                    dmc.ActionIcon(id="btn-stop", variant="outline", color="red", size="lg", children=DashIconify(icon="carbon:stop-filled", width=16)),
                                                                                    dmc.ActionIcon(id="btn-restart", variant="outline", color="orange", size="lg", children=DashIconify(icon="carbon:restart", width=16)),
                                                                                ],
                                                                            ),
                                                                        ],
                                                                    ),
                                                                    dmc.Paper(
                                                                        id="console-output", radius="sm", p="sm", withBorder=True,
                                                                        style={"height": "calc(100% - 56px)", "backgroundColor": "#111214", "color": "#e6eef8", "fontFamily": "monospace", "fontSize": "12px", "overflowY": "auto", "whiteSpace": "pre-wrap"},
                                                                    ),
                                                                ],
                                                            )
                                                        ],
                                                    ),

                                                    # --- TAB 3: GRAPHS ---
                                                    dmc.TabsPanel(
                                                        value="graphs",
                                                        children=[
                                                            dmc.Group(
                                                                justify="space-between", align="center",
                                                                style={"padding": "10px 16px", "backgroundColor": "#fff"},
                                                                children=[
                                                                    dmc.Group(
                                                                        gap="sm",
                                                                        children=[
                                                                            dmc.Select(id="graph-sheet-select", placeholder="Choose sheet", data=[], style={"width": 200}, searchable=True, clearable=False),
                                                                            dmc.Select(id="graph-metric-select", placeholder="Choose metric", data=[], style={"width": 240}, searchable=True, clearable=False),
                                                                        ],
                                                                    ),
                                                                    dmc.Group(
                                                                        gap="xs",
                                                                        children=[
                                                                            dmc.Button("Export CSV", id="export-csv", size="sm", leftSection=DashIconify(icon="carbon:download", width=14)),
                                                                            dmc.Button("Clear", id="clear-graph", size="sm", variant="outline", leftSection=DashIconify(icon="carbon:eraser", width=14)),
                                                                        ],
                                                                    ),
                                                                ],
                                                            ),
                                                            dmc.Divider(variant="solid"),
                                                            dmc.Card(
                                                                radius="md", p="md", withBorder=False, style={"height": "75vh"},
                                                                children=[
                                                                    html.Div(id="graph-container", style={"height": "100%", "width": "100%"}),
                                                                    html.Div(id="best-model-display", style={"display": "none"}),
                                                                    html.Div(id="best-model-error", style={"display": "none"}),
                                                                ],
                                                            ),
                                                        ],
                                                    ),

                                                    dmc.TabsPanel(
                                                        value="artifacts",
                                                        children=[
                                                            # Top Controls
                                                            dmc.Group(
                                                                justify="flex-start", align="center",
                                                                style={"padding": "10px 16px", "backgroundColor": "#fff", "borderBottom": "1px solid #eee"},
                                                                children=[
                                                                    dmc.Text("Select Result:", size="sm", fw=500),
                                                                    dmc.Select(id="artifact-sheet-select", placeholder="Choose sheet", data=[], style={"width": 200}, searchable=True, clearable=False),
                                                                    dmc.Select(id="artifact-metric-select", placeholder="Choose metric", data=[], style={"width": 240}, searchable=True, clearable=False),
                                                                ],
                                                            ),

                                                            # Inner Tabs
                                                            dmc.Tabs(
                                                                value="treatment", # <--- CHANGED DEFAULT TO OUR NEW TAB
                                                                variant="pills",
                                                                color="indigo",
                                                                style={"padding": "10px"},
                                                                children=[
                                                                    dmc.TabsList(
                                                                        children=[
                                                                            dmc.TabsTab("Data Treatment", value="treatment"), # <--- NEW TAB
                                                                            dmc.TabsTab("Stationarity Test", value="stationarity"),
                                                                            dmc.TabsTab("Seasonal Decomposition", value="decomposition"),
                                                                            dmc.TabsTab("Auto Correlation", value="acf_pacf"),
                                                                            dmc.TabsTab("Y Distribution", value="distribution"),
                                                                            dmc.TabsTab("Feature Analysis", value="features"),
                                                                            dmc.TabsTab("Experiment Details", value="experiments"),
                                                                        ]
                                                                    ),
                                                                    
                                                                    dmc.Space(h=10),

                                                                    # 0. DATA TREATMENT (NEW)
                                                                    dmc.TabsPanel(
                                                                        value="treatment",
                                                                        children=[
                                                                            dmc.Card(
                                                                                withBorder=True, radius="md", p="md",
                                                                                style={"height": "65vh", "overflowY": "auto"},
                                                                                children=[
                                                                                    dmc.Text("Data Treatment Analysis (Before vs After)", fw=700, size="lg", mb="sm"),
                                                                                    dcc.Graph(id="treatment-graph", style={"height": "400px", "minHeight": "400px"}),
                                                                                    dmc.Grid([
                                                                                        dmc.GridCol(
                                                                                            children=[
                                                                                                dmc.Text("Target (Y) Treatment Profile", fw=600, size="sm"),
                                                                                                html.Pre(id="y-treatment-json", style={
                                                                                                    "backgroundColor": "#f8f9fa", "padding": "10px", 
                                                                                                    "borderRadius": "5px", "overflowX": "auto", "fontSize": "12px",
                                                                                                    "border": "1px solid #dee2e6"
                                                                                                })
                                                                                            ], span=6
                                                                                        ),
                                                                                        dmc.GridCol(
                                                                                            children=[
                                                                                                dmc.Text("Features (X) Treatment Profiles", fw=600, size="sm"),
                                                                                                html.Pre(id="x-treatment-json", style={
                                                                                                    "backgroundColor": "#f8f9fa", "padding": "10px", 
                                                                                                    "borderRadius": "5px", "overflowX": "auto", "fontSize": "12px",
                                                                                                    "border": "1px solid #dee2e6"
                                                                                                })
                                                                                            ], span=6
                                                                                        )
                                                                                    ], gutter="md", style={"marginTop": "20px"})
                                                                                ]
                                                                            )
                                                                        ]
                                                                    ),

                                                                    # 1. DECOMPOSITION
                                                                    dmc.TabsPanel(
                                                                        value="decomposition",
                                                                        children=[
                                                                            dmc.Card(
                                                                                withBorder=True, radius="md", p="md",
                                                                                style={"height": "65vh", "overflowY": "auto"},
                                                                                children=[
                                                                                    dcc.Graph(id="decomposition-graph", style={"minHeight": "1100px"}) 
                                                                                ]
                                                                            )
                                                                        ]
                                                                    ),

                                                                    # 2. STATIONARITY
                                                                    dmc.TabsPanel(
                                                                        value="stationarity",
                                                                        children=[
                                                                            dmc.Card(
                                                                                withBorder=True, radius="md", p="md",
                                                                                style={"height": "65vh", "overflowY": "auto"},
                                                                                children=[
                                                                                    dcc.Graph(id="stationarity-graph", style={"minHeight": "600px"})
                                                                                ]
                                                                            )
                                                                        ]
                                                                    ),

                                                                    # 3. ACF/PACF
                                                                    dmc.TabsPanel(
                                                                        value="acf_pacf",
                                                                        children=[
                                                                            dmc.Card(
                                                                                withBorder=True, radius="md", p="md",
                                                                                style={"height": "65vh", "overflowY": "auto"},
                                                                                children=[
                                                                                    dcc.Graph(id="acf-pacf-graph", style={"minHeight": "700px"})
                                                                                ]
                                                                            )
                                                                        ]
                                                                    ),

                                                                    # 4. FEATURES
                                                                    dmc.TabsPanel(
                                                                        value="features",
                                                                        children=[
                                                                            dmc.Card(
                                                                                withBorder=True, radius="md", p="md",
                                                                                style={"height": "65vh", "overflowY": "auto"},
                                                                                children=[
                                                                                    dcc.Graph(id="features-graph", style={"minHeight": "700px"})
                                                                                ]
                                                                            )
                                                                        ]
                                                                    ),

                                                                    # 5. DISTRIBUTION
                                                                    dmc.TabsPanel(
                                                                        value="distribution",
                                                                        children=[
                                                                            dmc.Card(
                                                                                withBorder=True, radius="md", p="md",
                                                                                style={"height": "65vh", "overflowY": "auto"},
                                                                                children=[
                                                                                    dcc.Graph(id="distribution-graph", style={"minHeight": "500px"})
                                                                                ]
                                                                            )
                                                                        ]
                                                                    ),

                                                                    # 6. EXPERIMENTS
                                                                    dmc.TabsPanel(
                                                                        value="experiments",
                                                                        children=[
                                                                            dmc.Card(
                                                                                withBorder=True, radius="md", p="md",
                                                                                style={"height": "65vh", "overflowY": "auto"},
                                                                                children=[
                                                                                    dmc.Group(
                                                                                        align="center",
                                                                                        children=[
                                                                                            dmc.Text("Select Performance Metric:", size="sm", fw=500),
                                                                                            dmc.Select(
                                                                                                id="experiment-perf-metric",
                                                                                                data=[
                                                                                                    {"label": "WMAPE (Weighted Error)", "value": "WMAPE"},
                                                                                                    {"label": "MAPE (Mean % Error)", "value": "MAPE"},
                                                                                                    {"label": "MAE (Mean Abs Error)", "value": "MAE"},
                                                                                                    {"label": "Accuracy (%)", "value": "Accuracy"}
                                                                                                ],
                                                                                                value="WMAPE",
                                                                                                style={"width": 250},
                                                                                                clearable=False
                                                                                            ),
                                                                                        ],
                                                                                        style={"marginBottom": 15}
                                                                                    ),

                                                                                    dcc.Graph(id="experiment-graph", style={"minHeight": "600px"}) 
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
                ],
            ),
        ],
    )