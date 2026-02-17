import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

from components.header import create_header
from components.sidebar import create_sidebar
from components.toolbar import create_toolbar


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
                    
                    # 1. NEW TOOLBAR (Replaces Sidebar)
                    create_toolbar(),
                    
                    dmc.Space(h="md"),

                    # 2. Main Content Area (Full Width)
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
                                                                dmc.TabsTab("Features Analysis (X)", value="tab-x", leftSection=DashIconify(icon="carbon:data-1", width=16)),
                                                                dmc.TabsTab("Target Analysis (Y)", value="tab-y", leftSection=DashIconify(icon="carbon:chart-line-data", width=16)),
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
                                                                                dmc.TabsTab("Data Statistics", value="x-health", leftSection=DashIconify(icon="carbon:report-data", width=16)),
                                                                                dmc.TabsTab("Collinearity ", value="x-collinear", leftSection=DashIconify(icon="carbon:heat-map", width=16)),
                                                                                dmc.TabsTab("X Distribution", value="x-dist", leftSection=DashIconify(icon="carbon:histogram", width=16)),
                                                                            ]),
                                                                            dmc.Space(h=15),
                                                                            
                                                                            # Sub-Tab: Data Statistics
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
                                                                                    dmc.Card(withBorder=True, radius="md", p="md", style={"height": "70vh", "display": "flex", "flexDirection": "column"}, children=[
                                                                                        dcc.Graph(id="kyd-features-graph", responsive=True, style={"flex": 1, "width": "100%"})
                                                                                    ])
                                                                                ]
                                                                            ),
                                                                            
                                                                            # Sub-Tab: X Distributions
                                                                            dmc.TabsPanel(
                                                                                value="x-dist",
                                                                                children=[
                                                                                    # 1. Plot Type Toggle
                                                                                    dmc.Group(
                                                                                        justify="flex-end",
                                                                                        mb="xs", 
                                                                                        children=[
                                                                                            dmc.RadioGroup(
                                                                                                id="kyd-x-plot-type",
                                                                                                value="histogram", 
                                                                                                size="sm", 
                                                                                                # FIX: Use dmc.Group inside children for horizontal layout
                                                                                                children=dmc.Group(
                                                                                                    gap="md",
                                                                                                    children=[
                                                                                                        dmc.Radio(label="Histogram", value="histogram"),
                                                                                                        dmc.Radio(label="Box Plot", value="boxplot"),
                                                                                                        dmc.Radio(label="Scatter Plot", value="scatterplot"),
                                                                                                    ]
                                                                                                )
                                                                                            )
                                                                                        ]
                                                                                    ),
                                                                                    # 2. Graph Card
                                                                                    dmc.Card(
                                                                                        withBorder=True, 
                                                                                        radius="md", 
                                                                                        p="md", 
                                                                                        style={"height": "65vh", "display": "flex", "flexDirection": "column"}, 
                                                                                        children=[
                                                                                            dcc.Graph(id="kyd-x-distribution-graph", responsive=True, style={"flex": 1, "width": "100%", "minHeight": "350px"})
                                                                                        ]
                                                                                    )
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
                                                                                dmc.TabsTab("Lag Analysis", value="y-acf"),
                                                                                dmc.TabsTab("Y Distribution", value="y-dist"),
                                                                            ]),
                                                                            dmc.Space(h=15),

                                                                            # Sub-Tab: Stationarity
                                                                            dmc.TabsPanel(
                                                                                value="y-stat",
                                                                                children=[
                                                                                    dmc.Card(withBorder=True, radius="md", p="md", style={"height": "70vh", "display": "flex", "flexDirection": "column"}, children=[
                                                                                        dcc.Graph(id="kyd-stationarity-graph", responsive=True, style={"flex": 1, "width": "100%"})
                                                                                    ])
                                                                                ]
                                                                            ),
                                                                            
                                                                            # Sub-Tab: Decomposition
                                                                            dmc.TabsPanel(
                                                                                value="y-decomp",
                                                                                children=[
                                                                                    dmc.Card(withBorder=True, radius="md", p="md", style={"height": "70vh", "overflowY": "auto"}, children=[
                                                                                        dcc.Graph(id="kyd-decomposition-graph", responsive=True, style={"width": "100%", "minHeight": "800px"})
                                                                                    ])
                                                                                ]
                                                                            ),

                                                                            # Sub-Tab: ACF/PACF
                                                                            dmc.TabsPanel(
                                                                                value="y-acf",
                                                                                children=[
                                                                                    dmc.Card(withBorder=True, radius="md", p="md", style={"height": "70vh", "display": "flex", "flexDirection": "column"}, children=[
                                                                                        dcc.Graph(id="kyd-acf-pacf-graph", responsive=True, style={"flex": 1, "width": "100%", "minHeight": "400px"})
                                                                                    ])
                                                                                ]
                                                                            ),
                                                                            
                                                                            # Sub-Tab: Y Distribution
                                                                            dmc.TabsPanel(
                                                                                value="y-dist",
                                                                                children=[
                                                                                    # 1. Plot Type Toggle
                                                                                    dmc.Group(
                                                                                        justify="flex-end",
                                                                                        mb="xs",
                                                                                        children=[
                                                                                            dmc.RadioGroup(
                                                                                                id="kyd-y-plot-type",
                                                                                                value="histogram",
                                                                                                size="sm",
                                                                                                children=dmc.Group(
                                                                                                    gap="md",
                                                                                                    children=[
                                                                                                        dmc.Radio(label="Histogram", value="histogram"),
                                                                                                        dmc.Radio(label="Box Plot", value="boxplot"),
                                                                                                        dmc.Radio(label="Scatter Plot", value="scatterplot"),
                                                                                                    ]
                                                                                                )
                                                                                            )
                                                                                        ]
                                                                                    ),
                                                                                    # 2. Graph Card
                                                                                    dmc.Card(
                                                                                        withBorder=True, 
                                                                                        radius="md", 
                                                                                        p="md", 
                                                                                        style={"height": "65vh", "display": "flex", "flexDirection": "column"}, 
                                                                                        children=[
                                                                                            dcc.Graph(id="kyd-y-distribution-graph", responsive=True, style={"flex": 1, "width": "100%", "minHeight": "350px"})
                                                                                        ]
                                                                                    )
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
                                                                    dmc.Button("Download Logs", id="btn-download-log", size="xs", leftSection=DashIconify(icon="carbon:download", width=14)),
                                                                    # dmc.ActionIcon(id="btn-stop", variant="outline", color="red", size="lg", children=DashIconify(icon="carbon:stop-filled", width=16)),
                                                                    # dmc.ActionIcon(id="btn-restart", variant="outline", color="orange", size="lg", children=DashIconify(icon="carbon:restart", width=16)),
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

                                    # --- TAB 3: Forecast ---
                                    dmc.TabsPanel(
                                        value="graphs",
                                        children=[
                                            dmc.Group(
                                                justify="flex-end", align="center",
                                                style={"padding": "10px 16px", "backgroundColor": "#fff"},
                                                children=[
                                                    dmc.Group(
                                                        gap="xs",
                                                        children=[
                                                            dmc.Button("Export CSV", id="export-csv", size="sm", leftSection=DashIconify(icon="carbon:download", width=14)),
                                                            # dmc.Button("Clear", id="clear-graph", size="sm", variant="outline", leftSection=DashIconify(icon="carbon:eraser", width=14)),
                                                        ],
                                                    ),
                                                ],
                                            ),
                                            dmc.Divider(variant="solid"),
                                            dmc.Card(
                                                radius="md", p="md", withBorder=False, style={"height": "75vh", "display": "flex", "flexDirection": "column"},
                                                children=[
                                                    html.Div(id="graph-container", style={"flex": 1, "width": "100%"}),
                                                    html.Div(id="best-model-display", style={"display": "none"}),
                                                    html.Div(id="best-model-error", style={"display": "none"}),
                                                ],
                                            ),
                                        ],
                                    ),

                                    # --- TAB 4: ARTIFACTS ---
                                    dmc.TabsPanel(
                                        value="artifacts",
                                        children=[
                                            # Top Controls (Responsive Flex Group)
                                            dmc.Group(
                                                justify="flex-start", align="flex-end",
                                                style={"padding": "10px 16px", "backgroundColor": "#fff", "borderBottom": "1px solid #eee"},                                
                                            ),
                                            # Inner Tabs
                                            dmc.Tabs(
                                                value="treatment", 
                                                variant="pills",
                                                color="indigo",
                                                style={"padding": "10px"},
                                                children=[
                                                    dmc.TabsList(
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
                                                    
                                                    dmc.Space(h=10),

                                                    # 0. DATA TREATMENT
                                                    dmc.TabsPanel(
                                                        value="treatment",
                                                        children=[
                                                            dmc.Card(
                                                                withBorder=True, radius="md", p="md",
                                                                style={"height": "70vh", "display": "flex", "flexDirection": "column", "overflowY": "auto"},
                                                                children=[
                                                                    dmc.Text("Data Treatment Analysis (Before vs After)", fw=700, size="lg", mb="sm"),
                                                                    dcc.Graph(id="treatment-graph", responsive=True, style={"flex": 1, "width": "100%", "minHeight": "300px"}),
                                                                    dmc.Grid([
                                                                        dmc.GridCol(
                                                                            children=[
                                                                                dmc.Text(id="y-treatment-title", fw=600, size="sm"),
                                                                                html.Pre(id="y-treatment-json", style={
                                                                                    "backgroundColor": "#f8f9fa", "padding": "10px", 
                                                                                    "borderRadius": "5px", "overflowX": "auto", "fontSize": "12px",
                                                                                    "border": "1px solid #dee2e6"
                                                                                })
                                                                            ], span={"base": 12, "md": 6} 
                                                                        ),
                                                                        dmc.GridCol(
                                                                            children=[
                                                                                dmc.Text("Features (X) Treatment Profiles", fw=600, size="sm"),
                                                                                html.Pre(id="x-treatment-json", style={
                                                                                    "backgroundColor": "#f8f9fa", "padding": "10px", 
                                                                                    "borderRadius": "5px", "overflowX": "auto", "fontSize": "12px",
                                                                                    "border": "1px solid #dee2e6"
                                                                                })
                                                                            ], span={"base": 12, "md": 6} 
                                                                        )
                                                                    ], gutter="md", style={"marginTop": "20px", "flexShrink": 0})
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
                                                                style={"height": "70vh", "overflowY": "auto"},
                                                                children=[ dcc.Graph(id="decomposition-graph", responsive=True, style={"width": "100%", "minHeight": "800px"}) ]
                                                            )
                                                        ]
                                                    ),

                                                    # 2. STATIONARITY
                                                    dmc.TabsPanel(
                                                        value="stationarity",
                                                        children=[
                                                            dmc.Card(
                                                                withBorder=True, radius="md", p="md",
                                                                style={"height": "70vh", "display": "flex", "flexDirection": "column"},
                                                                children=[ dcc.Graph(id="stationarity-graph", responsive=True, style={"flex": 1, "width": "100%"}) ]
                                                            )
                                                        ]
                                                    ),

                                                    # 3. ACF/PACF
                                                    dmc.TabsPanel(
                                                        value="acf_pacf",
                                                        children=[
                                                            dmc.Card(
                                                                withBorder=True, radius="md", p="md",
                                                                style={"height": "70vh", "display": "flex", "flexDirection": "column"},
                                                                children=[ dcc.Graph(id="acf-pacf-graph", responsive=True, style={"flex": 1, "width": "100%", "minHeight": "400px"}) ]
                                                            )
                                                        ]
                                                    ),

                                                    # 4. FEATURES
                                                    dmc.TabsPanel(
                                                        value="features",
                                                        children=[
                                                            dmc.Card(
                                                                withBorder=True, radius="md", p="md",
                                                                style={"height": "70vh", "display": "flex", "flexDirection": "column", "overflowY": "auto"},
                                                                children=[ dcc.Graph(id="features-graph", responsive=True, style={"flex": 1, "width": "100%", "minHeight": "400px"}) ]
                                                            )
                                                        ]
                                                    ),

                                                    # 5. DISTRIBUTION
                                                    dmc.TabsPanel(
                                                        value="distribution",
                                                        children=[
                                                            # 1. Plot Type Toggle
                                                            dmc.Group(
                                                                justify="flex-end",
                                                                mb="xs",
                                                                children=[
                                                                    dmc.RadioGroup(
                                                                        id="artifact-y-plot-type", # Unique ID for Artifacts tab
                                                                        value="histogram",
                                                                        size="sm",
                                                                        children=dmc.Group(
                                                                            gap="md",
                                                                            children=[
                                                                                dmc.Radio(label="Histogram", value="histogram"),
                                                                                dmc.Radio(label="Box Plot", value="boxplot"),
                                                                                dmc.Radio(label="Scatter Plot", value="scatterplot"),
                                                                            ]
                                                                        )
                                                                    )
                                                                ]
                                                            ),
                                                            # 2. Graph Card
                                                            dmc.Card(
                                                                withBorder=True, 
                                                                radius="md", 
                                                                p="md", 
                                                                style={"height": "70vh", "display": "flex", "flexDirection": "column"}, 
                                                                children=[
                                                                    dcc.Graph(id="distribution-graph", responsive=True, style={"flex": 1, "width": "100%", "minHeight": "350px"})
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
                                                                style={"height": "70vh", "display": "flex", "flexDirection": "column"},
                                                                children=[
                                                                    dmc.Group(
                                                                        align="center",
                                                                        children=[
                                                                            dmc.Select(
                                                                                id="experiment-perf-metric",
                                                                                label="Select Performance Metric",
                                                                                data=[
                                                                                    {"label": "WMAPE (Weighted Error)", "value": "WMAPE"},
                                                                                    {"label": "MAPE (Mean % Error)", "value": "MAPE"},
                                                                                    {"label": "MAE (Mean Abs Error)", "value": "MAE"},
                                                                                    {"label": "Accuracy (%)", "value": "Accuracy"}
                                                                                ],
                                                                                value="WMAPE",
                                                                                style={"minWidth": "250px", "flex": "0 1 auto"},
                                                                                clearable=False
                                                                            ),
                                                                        ],
                                                                        style={"marginBottom": 15, "flexShrink": 0}
                                                                    ),
                                                                    dcc.Graph(id="experiment-graph", responsive=True, style={"flex": 1, "width": "100%", "minHeight": "400px"}) 
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