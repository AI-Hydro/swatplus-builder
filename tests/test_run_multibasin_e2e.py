from __future__ import annotations

from textwrap import dedent

from scripts.run_multibasin_e2e import parse_terminal_channel_ids


def test_parse_terminal_channel_ids_uses_gis_id(tmp_path) -> None:
    txt = tmp_path / "TxtInOut"
    txt.mkdir()
    p = txt / "chandeg.con"
    p.write_text(
        dedent(
            """\
            chandeg.con
            id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac
            100 cha0100 7 0 0 0 0 1 s 0 0 0 1 out 1 tot 1.0
            101 cha0101 8 0 0 0 0 1 s 0 0 0 1 sdc 1 tot 1.0
            """
        ),
        encoding="utf-8",
    )

    assert parse_terminal_channel_ids(txt) == {7}
