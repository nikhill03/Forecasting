import dash_mantine_components as dmc
from dash_iconify import DashIconify
from dash import html

def create_header():
    return dmc.Paper(
        shadow="sm", p="md",
        style={
            "position": "sticky", "top": 0, "zIndex": 100,
            "backgroundColor": "white",
            "borderBottom": "1px solid #eaeaea",
            "borderTop": "4px solid #005eb8"
        },
        children=dmc.Container(fluid=True, children=dmc.Group(justify="space-between", children=[

            # Branding
            dmc.Group(gap="md", children=[
                html.Img(
                    src="https://upload.wikimedia.org/wikipedia/commons/a/a0/Genpact_logo.svg",
                    style={"height": "32px", "marginTop": "2px"}
                ),
                dmc.Divider(orientation="vertical", h=35),
                dmc.Text(
                    "Capacity Forecast",
                    size="20px", fw=600, c="#495057",
                    visibleFrom="sm"
                )
            ]),

            # Utilities
            dmc.Group(gap="lg", children=[
                dmc.Box(
                    visibleFrom="md",
                    children=dmc.TextInput(
                        placeholder="Search campaigns.",
                        leftSection=DashIconify(icon="carbon:search", width=16, color="#adb5bd"),
                        radius="xl", size="sm", style={"width": "280px"}
                    )
                ),
                dmc.Group(gap="sm", children=[
                    dmc.ActionIcon(
                        variant="subtle", color="gray", size="lg", radius="xl",
                        children=DashIconify(icon="carbon:notification", width=20)
                    ),
                    dmc.ActionIcon(
                        variant="subtle", color="gray", size="lg", radius="xl",
                        children=DashIconify(icon="carbon:help", width=20)
                    ),
                ]),
                dmc.Divider(orientation="vertical", h=30),
                dmc.Group(gap="sm", children=[
                    dmc.Stack(gap=0, align="flex-end", children=[
                        dmc.Text("Admin User", size="sm", fw=600, c="dark"),
                        dmc.Text("Data Analyst", size="xs", c="dimmed"),
                    ]),
                    dmc.Avatar(size="md", radius="xl", color="blue", variant="filled", children="AD")
                ])
            ])
        ]))
    )
