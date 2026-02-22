# components/upload_box.py
from dash import dcc, html
import dash_mantine_components as dmc

def render_upload(component_id: str, label: str):
    message_id = f"{component_id}-message"

    return dmc.Stack(gap="xs", children=[
        dmc.Text(label, size="sm", fw=700),
        dcc.Upload(
            id=component_id, # Use the exact ID passed
            children=html.Div([
                html.Div("⬆ Upload File"),
                html.Div("(.xlsx, .csv)", style={"fontSize": "10px", "color": "#666"})
            ], style={"paddingTop": "8px"}),
            accept=".xlsx,.xls,.csv",
            style={
                "width": "140px", # Fixed width for toolbar look
                "height": "50px", # Shorter height for toolbar
                "lineHeight": "16px",
                "borderWidth": "1px",
                "borderStyle": "dashed",
                "borderRadius": "4px",
                "textAlign": "center",
                "cursor": "pointer",
                "backgroundColor": "#fafafa",
                "display": "flex", 
                "flexDirection": "column", 
                "justifyContent": "center"
            },
            multiple=False,
        ),
        html.Div(id=message_id, style={"fontSize": "10px", "color": "#555", "height": "15px"})
    ])