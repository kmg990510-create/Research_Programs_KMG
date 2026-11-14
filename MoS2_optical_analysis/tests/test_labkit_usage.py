"""The GUI uses the shared lab code (labkit) for the theme, sidebar sections and figure sizes."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import gui  # noqa: E402,F401  (puts the repository root on sys.path so that labkit is found)
from gui.components import figure_sizes  # noqa: E402
from gui.components.report_loader import sidebar_section  # noqa: E402
from labkit import sidebar as labkit_sidebar  # noqa: E402

GUI_DIR = PROJECT_ROOT / "gui"


def _sources() -> dict[str, str]:
    files = [*GUI_DIR.glob("pages/*.py"), *GUI_DIR.glob("components/*.py"), GUI_DIR / "Main.py"]
    return {path.relative_to(PROJECT_ROOT).as_posix(): path.read_text(encoding="utf-8-sig") for path in files}


def test_sidebar_section_is_the_shared_one() -> None:
    assert sidebar_section is labkit_sidebar.sidebar_section
    assert not (GUI_DIR / "components" / "paper_theme.py").exists()  # replaced by labkit.plot_theme


def test_no_figure_is_drawn_without_the_size_inputs() -> None:
    direct = [name for name, text in _sources().items() if re.search(r"\bplotly_chart\(|\bst\.pyplot\(", text)]
    assert direct == []  # every figure goes through figure_sizes.show


def test_every_kind_is_used_and_has_inputs_on_its_page() -> None:
    sources = _sources()
    shown: dict[str, set[str]] = {}  # file -> kinds drawn there
    for name, text in sources.items():
        kinds = set(re.findall(r"\bshow\(\s*\w+,\s*\"(\w+)\"", text)) | set(re.findall(r"_show_styled\(fig, \"(\w+)\"\)", text))
        if "def _show_styled(fig: go.Figure, kind: str = \"sample_scatter\")" in text:
            kinds.add("sample_scatter")
        if kinds:
            shown[name] = kinds
    used = set().union(*shown.values())
    assert used <= set(figure_sizes.KINDS)
    assert set(figure_sizes.KINDS) == used

    # a page that draws a kind itself must offer the inputs for it
    for name, kinds in shown.items():
        if "/pages/" not in name:
            continue
        section = re.search(r"figure_size_section\(\"\d\) Figure size\", \[([^\]]*)\]\)", sources[name])
        assert section, name
        offered = set(re.findall(r"\"(\w+)\"", section.group(1)))
        assert kinds <= offered, (name, kinds - offered)


def test_pages_that_draw_spectra_offer_the_spectrum_size() -> None:
    sources = _sources()
    for name, text in sources.items():
        if "/pages/" in name and "render_spectrum_overlay(" in text:
            assert re.search(r"figure_size_section\(.*\"spectrum\"", text), name
        if "/pages/" in name and "render_metric_histogram(" in text:
            assert re.search(r"figure_size_section\(.*\"model_charts\"", text), name


def test_packaging_includes_labkit() -> None:
    spec = (PROJECT_ROOT / "packaging" / "mos2_optical_analysis.spec").read_text(encoding="utf-8-sig")
    assert '_safe_collect_submodules("labkit")' in spec and "str(REPO_ROOT)" in spec
    dockerfile = (PROJECT_ROOT.parent / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY --chown=user:user labkit/ $HOME/app/labkit/" in dockerfile


def test_a_figure_follows_the_sidebar_size_even_when_it_is_drawn_first() -> None:
    import json

    from streamlit.testing.v1 import AppTest

    def app() -> None:
        import plotly.graph_objects as go

        from gui.components.figure_sizes import figure_size_section, show

        show(go.Figure(go.Scatter(x=[1, 2], y=[1, 2])), "spectrum", key="figure")  # drawn before the inputs
        figure_size_section("1) Figure size", ["spectrum"])

    def layout(at: AppTest) -> dict:
        return json.loads(at.get("plotly_chart")[0].proto.spec)["layout"]

    # AppTest swaps sys.modules['__main__']; put it back, or a later test that starts worker processes hangs
    main_module = sys.modules["__main__"]
    try:
        _check_size_follows_sidebar(AppTest.from_function(app, default_timeout=60), layout)
    finally:
        sys.modules["__main__"] = main_module


def _check_size_follows_sidebar(at, layout) -> None:
    at.run()
    assert [str(e.value) for e in at.exception] == []
    assert layout(at).get("width") is None and layout(at)["height"] == figure_sizes.KINDS["spectrum"][2]
    assert at.sidebar.number_input[0].disabled  # width follows the page until "fit" is switched off

    at.sidebar.checkbox[0].set_value(False)
    at.run()
    at.sidebar.number_input[0].set_value(610)
    at.sidebar.number_input[1].set_value(330)
    at.run()
    assert (layout(at)["width"], layout(at)["height"]) == (610, 330)
