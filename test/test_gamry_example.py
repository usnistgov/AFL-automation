import ast
import pathlib

from jinja2 import Template


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
GAMRY_DRIVER_PATH = REPO_ROOT / "AFL" / "automation" / "instrument" / "Gamry" / "GamryDriver.py"
GAMRY_PANEL_DIR = REPO_ROOT / "AFL" / "automation" / "apps" / "gamry_panel"


def _module_assignments(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assignments = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                assignments[node.targets[0].id] = ast.literal_eval(node.value)
            except Exception:
                continue
    return assignments


def test_launcher_metadata_matches_driver_module():
    assignments = _module_assignments(GAMRY_DRIVER_PATH)

    assert assignments["_DEFAULT_PORT"] == 5051
    assert assignments["_DEFAULT_CUSTOM_CONFIG"] == {
        "_classname": "AFL.automation.instrument.Gamry.GamryDriver.GamryDriver",
    }


def test_gamry_panel_assets_are_packaged_with_driver():
    assert GAMRY_PANEL_DIR.is_dir()
    assert (GAMRY_PANEL_DIR / "gamry_panel.html").is_file()
    assert (GAMRY_PANEL_DIR / "gamry_panel.css").is_file()
    assert (GAMRY_PANEL_DIR / "gamry_panel.js").is_file()


def test_gamry_driver_source_registers_panel_route_and_assets():
    source = GAMRY_DRIVER_PATH.read_text(encoding="utf-8")

    assert "self.useful_links['Gamry Panel'] = '/gamry_panel'" in source
    assert "'gamry_panel_assets': pathlib.Path(__file__).parent.parent.parent / 'apps' / 'gamry_panel'" in source
    assert "def gamry_panel(self, **kwargs):" in source


def test_gamry_panel_template_renders_inline_assets():
    rendered = Template((GAMRY_PANEL_DIR / "gamry_panel.html").read_text(encoding="utf-8")).render(
        inline_css=(GAMRY_PANEL_DIR / "gamry_panel.css").read_text(encoding="utf-8"),
        inline_js=(GAMRY_PANEL_DIR / "gamry_panel.js").read_text(encoding="utf-8"),
    )

    assert "<title>Gamry Panel</title>" in rendered
    assert "Remote Front Panel" in rendered
    assert "{{ inline_css }}" not in rendered
    assert "{{ inline_js }}" not in rendered
    assert "--accent: #0f766e;" in rendered
    assert "ensureAuthToken" in rendered
