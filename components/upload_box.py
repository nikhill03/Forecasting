# components/upload_box.py
from dash import dcc, html
import dash_mantine_components as dmc

def render_upload(label: str, id_prefix: str = "article"):
    upload_id = f"{id_prefix}-upload"
    message_id = f"{id_prefix}-message"

    return dmc.Stack(gap="xs", children=[
        dmc.Text(label, size="sm", fw=700),
        dcc.Upload(
            id=upload_id,
            children=html.Div([
                html.Div("⬆ Drag & drop or click to upload an Excel file (.xlsx, .xls, .csv)"),
                html.Div("(Single file only)", style={"fontSize": "11px", "color": "#666"})
            ], style={"paddingTop": "8px"}),
            accept=".xlsx,.xls,.csv",
            style={
                "width": "100%",
                "height": "72px",
                "lineHeight": "72px",
                "borderWidth": "2px",
                "borderStyle": "dashed",
                "borderRadius": "6px",
                "textAlign": "center",
                "cursor": "pointer",
                "backgroundColor": "#fafafa",
            },
            multiple=False,
        ),
        html.Div(id=message_id, style={"fontSize": "12px", "color": "#555"})
    ])
