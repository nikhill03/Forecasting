import dash_mantine_components as dmc
from dash_iconify import DashIconify
from dash import html

def create_header():
    return dmc.Paper(
        shadow="sm", 
        p="md",
        style={
            "position": "sticky", "top": 0, "zIndex": 100,
            "backgroundColor": "rgba(255, 255, 255, 0.98)",
            "backdropFilter": "blur(12px)",
            "borderBottom": "1px solid #f1f3f5",
            "borderTop": "4px solid #1a73e8" 
        },
        children=dmc.Container(
            fluid=True, 
            children=dmc.Group(
                justify="space-between", 
                children=[
                    dmc.Group(gap="lg", children=[
                        # --- Enhanced Logo ---
                        html.Img(
                            src="https://upload.wikimedia.org/wikipedia/commons/a/a0/Genpact_logo.svg",
                            style={
                                "height": "50px", 
                                "filter": "drop-shadow(0px 2px 4px rgba(0,0,0,0.1))",
                                "transition": "transform 0.2s ease",
                                "cursor": "pointer"
                            },
                        ),
                        
                        dmc.Divider(orientation="vertical", h=25, style={"opacity": 0.6}),
                        
                        # --- Beautified Project Name ---
                        dmc.Group(gap=0, children=[
                            dmc.Text(
                                "Forecast",
                                style={
                                    "fontSize": "26px", 
                                    "fontWeight": 800, 
                                    "fontFamily": "'Montserrat', sans-serif",
                                    "color": "#1c1e21",
                                    "letterSpacing": "-1px"
                                }
                            ),
                            dmc.Text(
                                "360",
                                style={
                                    "fontSize": "26px", 
                                    "fontWeight": 800, 
                                    "fontFamily": "'Montserrat', sans-serif",
                                    "background": "linear-gradient(45deg, #1a73e8 30%, #6a11cb 90%)",
                                    "WebkitBackgroundClip": "text",
                                    "WebkitTextFillColor": "transparent",
                                    "letterSpacing": "-1px",
                                    "marginLeft": "2px"
                                }
                            ),
                        ]),
                    ]),
                ]
            )
        )
    )