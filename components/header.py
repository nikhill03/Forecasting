import dash_mantine_components as dmc
from dash_iconify import DashIconify
from dash import html

def create_header():
    return dmc.Paper(
        shadow="sm", p="md",
        style={
            "position": "sticky", "top": 0, "zIndex": 100,
            "backgroundColor": "rgba(255, 255, 255, 0.95)",
            "backdropFilter": "blur(10px)",
            "borderBottom": "1px solid #eaeaea",
            "borderTop": "5px solid #1a73e8" 
        },
        children=dmc.Container(fluid=True, children=dmc.Group(justify="space-between", children=[
            dmc.Group(gap="md", children=[
                html.Img(
                    src="https://upload.wikimedia.org/wikipedia/commons/a/a0/Genpact_logo.svg",
                    style={"height": "30px"}
                ),
                dmc.Divider(orientation="vertical", h=30),
                dmc.Text(
                    "Capacity Forecast",
                    style={"fontSize": "22px", "fontWeight": 700, "letterSpacing": "-0.5px", "color": "#1c1e21"}
                )
            ]),
        ]))
    )