"""Regression tests for the needflow SVG status-background postprocessor
(CLAUDE-ADC-SPHINX-TRACE-GRAPH-STATUS-BACKGROUND-001, section N).

All tests use small synthetic SVG fixtures shaped like the actual
Sphinx-Needs/Graphviz needflow output (one <g class="node"> per node, a
<title> holding the Requirement ID, an <a xlink:href> wrapper, a <polygon>
shape, and <text> label lines) -- never against the real, large generated
graph (that is covered separately by building the real Sphinx site and
inspecting its actual output).
"""
import xml.etree.ElementTree as ET

import svg_status_background as sb

NS = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}"


def _node_svg(node_id, x0=0, y0=-100, x1=150, y1=0, link=True, extra=""):
    a_open = f'<a xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="../doc.html#{node_id}">' if link else ""
    a_close = "</a>" if link else ""
    return f"""
<g class="node">
<title>{node_id}</title>
<g id="a_{node_id}">{a_open}
<polygon fill="none" stroke="black" points="{x1},{y0} {x0},{y0} {x0},{y1} {x1},{y1} {x1},{y0}" />
{extra}
<text x="{x0+5}" y="{y0+15}" font-size="12">Some Requirement</text>
<text x="{x0+5}" y="{y1-5}">{node_id}</text>
{a_close}</g>
</g>
"""


def _svg_document(*node_blocks):
    body = "\n".join(node_blocks)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="500pt" height="500pt">
<g id="graph0" class="graph">
{body}
</g>
</svg>"""


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content)
    return str(path)


def _polygon_for(path, node_id):
    root = ET.parse(path).getroot()
    for g in root.iter(NS + "g"):
        if g.get("class") != "node":
            continue
        title = g.find(NS + "title")
        if title is not None and title.text and title.text.strip() == node_id:
            return g.find(f".//{NS}polygon")
    return None


# 1-3: RED / YELLOW / GREEN backgrounds ----------------------------------------

def test_red_requirement_gets_red_background(tmp_path):
    path = _write(tmp_path, "g.svg", _svg_document(_node_svg("SYS_REQ_001")))
    stats = sb.annotate_svg_file(path, {"SYS_REQ_001": sb.status_model.NOT_IMPLEMENTED})
    assert stats["colored"] == 1
    poly = _polygon_for(path, "SYS_REQ_001")
    assert poly.get("fill") == sb.BACKGROUND_FILL[sb.status_model.NOT_IMPLEMENTED] == "#ffcdd2"


def test_yellow_requirement_gets_yellow_background(tmp_path):
    path = _write(tmp_path, "g.svg", _svg_document(_node_svg("SUB_REQ_005")))
    sb.annotate_svg_file(path, {"SUB_REQ_005": sb.status_model.IMPLEMENTED_TEST_NIO})
    poly = _polygon_for(path, "SUB_REQ_005")
    assert poly.get("fill") == "#fff9c4"


def test_green_requirement_gets_green_background(tmp_path):
    path = _write(tmp_path, "g.svg", _svg_document(_node_svg("IF_REQ_012")))
    sb.annotate_svg_file(path, {"IF_REQ_012": sb.status_model.IMPLEMENTED_TEST_IO})
    poly = _polygon_for(path, "IF_REQ_012")
    assert poly.get("fill") == "#c8e6c9"


# 4-7: each Requirement type is processed --------------------------------------

def test_sys_req_is_processed(tmp_path):
    path = _write(tmp_path, "g.svg", _svg_document(_node_svg("SYS_REQ_020")))
    stats = sb.annotate_svg_file(path, {"SYS_REQ_020": sb.status_model.IMPLEMENTED_TEST_IO})
    assert stats["colored"] == 1


def test_arc_req_is_processed(tmp_path):
    path = _write(tmp_path, "g.svg", _svg_document(_node_svg("ARC_REQ_003")))
    stats = sb.annotate_svg_file(path, {"ARC_REQ_003": sb.status_model.IMPLEMENTED_TEST_IO})
    assert stats["colored"] == 1


def test_sub_req_is_processed(tmp_path):
    path = _write(tmp_path, "g.svg", _svg_document(_node_svg("SUB_REQ_003")))
    stats = sb.annotate_svg_file(path, {"SUB_REQ_003": sb.status_model.IMPLEMENTED_TEST_IO})
    assert stats["colored"] == 1


def test_if_req_is_processed(tmp_path):
    path = _write(tmp_path, "g.svg", _svg_document(_node_svg("IF_REQ_003")))
    stats = sb.annotate_svg_file(path, {"IF_REQ_003": sb.status_model.IMPLEMENTED_TEST_IO})
    assert stats["colored"] == 1


# 8: non-Requirement node remains without traffic-light background ------------

def test_non_requirement_node_remains_unchanged(tmp_path):
    path = _write(tmp_path, "g.svg", _svg_document(_node_svg("ARC_001"), _node_svg("SYS_REQ_001")))
    stats = sb.annotate_svg_file(path, {"SYS_REQ_001": sb.status_model.NOT_IMPLEMENTED})
    poly = _polygon_for(path, "ARC_001")
    assert poly.get("fill") == "none"
    assert poly.get("class") is None
    assert stats["total_requirement_nodes_seen"] == 1


# 9: unknown state fails closed -------------------------------------------------

def test_unknown_state_fails_closed_to_grey_never_green(tmp_path):
    path = _write(tmp_path, "g.svg", _svg_document(_node_svg("SYS_REQ_002")))
    sb.annotate_svg_file(path, {"SYS_REQ_002": "SOME_FUTURE_UNKNOWN_STATE"})
    poly = _polygon_for(path, "SYS_REQ_002")
    assert poly.get("fill") == sb.BACKGROUND_FILL_UNKNOWN
    assert poly.get("fill") not in sb.BACKGROUND_FILL.values()
    assert poly.get("fill") != "#c8e6c9"


# 10: old status dot is absent --------------------------------------------------

def test_legacy_status_dot_is_stripped(tmp_path):
    legacy_dot = '<circle class="adc-requirement-status-dot" cx="10" cy="10" r="9" fill="#43a047" />'
    node = _node_svg("IF_REQ_020", extra=legacy_dot)
    path = _write(tmp_path, "g.svg", _svg_document(node))
    sb.annotate_svg_file(path, {"IF_REQ_020": sb.status_model.NOT_IMPLEMENTED})
    root = ET.parse(path).getroot()
    dots = [c for c in root.iter(NS + "circle") if c.get("class") == "adc-requirement-status-dot"]
    assert dots == []


# 11-12: idempotency and state-transition replacement --------------------------

def test_second_processing_is_idempotent(tmp_path):
    path = _write(tmp_path, "g.svg", _svg_document(_node_svg("ARC_REQ_004")))
    status_map = {"ARC_REQ_004": sb.status_model.NOT_IMPLEMENTED}
    sb.annotate_svg_file(path, status_map)
    first = ET.tostring(_polygon_for(path, "ARC_REQ_004"))
    sb.annotate_svg_file(path, status_map)
    second = ET.tostring(_polygon_for(path, "ARC_REQ_004"))
    assert first == second
    # exactly one polygon still present for this node -- no stacking/duplication
    root = ET.parse(path).getroot()
    polys = [p for p in root.iter(NS + "polygon")]
    assert len(polys) == 1


def test_state_transition_replaces_background_cleanly(tmp_path):
    path = _write(tmp_path, "g.svg", _svg_document(_node_svg("ARC_REQ_005")))
    sb.annotate_svg_file(path, {"ARC_REQ_005": sb.status_model.NOT_IMPLEMENTED})
    assert _polygon_for(path, "ARC_REQ_005").get("fill") == "#ffcdd2"
    sb.annotate_svg_file(path, {"ARC_REQ_005": sb.status_model.IMPLEMENTED_TEST_NIO})
    assert _polygon_for(path, "ARC_REQ_005").get("fill") == "#fff9c4"
    sb.annotate_svg_file(path, {"ARC_REQ_005": sb.status_model.IMPLEMENTED_TEST_IO})
    poly = _polygon_for(path, "ARC_REQ_005")
    assert poly.get("fill") == "#c8e6c9"
    # still a single polygon element for the node after three transitions
    root = ET.parse(path).getroot()
    assert len([p for p in root.iter(NS + "polygon")]) == 1


# 13-14: text and links unchanged -----------------------------------------------

def test_node_text_remains_unchanged(tmp_path):
    path = _write(tmp_path, "g.svg", _svg_document(_node_svg("IF_REQ_001")))
    before = [t.text for t in ET.parse(path).getroot().iter(NS + "text")]
    sb.annotate_svg_file(path, {"IF_REQ_001": sb.status_model.IMPLEMENTED_TEST_IO})
    after = [t.text for t in ET.parse(path).getroot().iter(NS + "text")]
    assert before == after


def test_node_links_remain_unchanged(tmp_path):
    path = _write(tmp_path, "g.svg", _svg_document(_node_svg("SUB_REQ_010")))
    sb.annotate_svg_file(path, {"SUB_REQ_010": sb.status_model.NOT_IMPLEMENTED})
    root = ET.parse(path).getroot()
    anchors = list(root.iter(NS + "a"))
    assert len(anchors) == 1
    assert anchors[0].get(f"{XLINK}href") == "../doc.html#SUB_REQ_010"


# 15: malformed/missing node does not corrupt SVG -------------------------------

def test_node_without_title_is_skipped_without_corruption(tmp_path):
    broken_node = """
<g class="node">
<g id="a_x"><a xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="x.html">
<polygon points="10,0 0,0 0,-10 10,-10" />
<text>no title element here</text>
</a></g>
</g>
"""
    path = _write(tmp_path, "g.svg", _svg_document(broken_node, _node_svg("SYS_REQ_003")))
    stats = sb.annotate_svg_file(path, {"SYS_REQ_003": sb.status_model.NOT_IMPLEMENTED})
    assert stats is not None
    assert stats["colored"] == 1
    ET.parse(path)  # still valid


def test_node_without_a_shape_is_skipped_not_crashed(tmp_path):
    shapeless = """
<g class="node">
<title>SYS_REQ_004</title>
<text>no polygon or ellipse here</text>
</g>
"""
    path = _write(tmp_path, "g.svg", _svg_document(shapeless))
    stats = sb.annotate_svg_file(path, {"SYS_REQ_004": sb.status_model.NOT_IMPLEMENTED})
    assert stats["skipped_no_shape"] == 1
    assert stats["colored"] == 0
    ET.parse(path)


def test_malformed_svg_fails_clearly_and_leaves_file_unmodified(tmp_path):
    path = tmp_path / "broken.svg"
    original = "<svg><g class=\"node\"><title>SYS_REQ_005</unclosed>"
    path.write_text(original)
    result = sb.annotate_svg_file(str(path), {"SYS_REQ_005": sb.status_model.NOT_IMPLEMENTED})
    assert result is None
    assert path.read_text() == original


# 16: central status map is reused -----------------------------------------------

def test_compute_status_map_uses_the_same_central_function(tmp_path):
    import json
    needs_json = tmp_path / "needs.json"
    needs_json.write_text(json.dumps({
        "versions": {
            "v": {
                "needs": {
                    "IF_REQ_100": {"id": "IF_REQ_100", "type": "ifreq", "implements": [], "derived_from": []},
                }
            }
        }
    }))
    status_map = sb.compute_status_map_from_needs_json(str(needs_json))
    assert status_map["IF_REQ_100"] == sb.status_model.NOT_IMPLEMENTED


def test_compute_status_map_returns_empty_dict_when_needs_json_missing(tmp_path):
    assert sb.compute_status_map_from_needs_json(str(tmp_path / "does_not_exist.json")) == {}


# 17: build-hook integration (module-level wiring smoke test) -------------------

def test_postprocess_needflow_svgs_is_a_two_arg_build_finished_hook():
    import inspect
    sig = inspect.signature(sb.postprocess_needflow_svgs)
    assert list(sig.parameters) == ["app", "exception"]


def test_postprocess_needflow_svgs_noop_when_exception_present():
    class FakeApp:
        outdir = "/does/not/matter"
    # Must return without raising or touching anything when the build itself failed.
    sb.postprocess_needflow_svgs(FakeApp(), Exception("build failed"))


def test_postprocess_needflow_svgs_noop_when_needs_json_missing(tmp_path):
    class FakeApp:
        outdir = str(tmp_path)
    sb.postprocess_needflow_svgs(FakeApp(), None)  # must not raise
