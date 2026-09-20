"""Unit tests for the deterministic normalisation and comparison rules."""
from app.compare import compare_fields, count_equal, parties_equal, ports_equal, weight_equal
from app.extract import is_placeholder, parse_container_count, parse_weight_kg
from app.schemas import FieldValue


def fv(v):
    return FieldValue(value=v, evidence=f"line: {v}")


def test_party_names_ignore_punctuation_and_legal_suffix_format():
    assert parties_equal("KPP-ANTALIS (SINGAPORE) PTE. LTD.", "KPP-ANTALIS (SINGAPORE) PTE LTD")[0]
    assert parties_equal("MOORIM SP CO., LTD", "MOORIM SP CO LTD")[0]
    assert parties_equal("Ball & Doggett Australia Pty Ltd", "BALL AND DOGGETT AUSTRALIA PTY LTD")[0]


def test_party_names_detect_real_differences():
    assert not parties_equal("EAST BRIGHT FZ-LLC", "UAB NOVAKOPA")[0]
    # a longer form with a different legal entity is NOT the same party
    assert not parties_equal("APRIL FINE PAPER TRADING", "APRIL FINE PAPER TRADING (MIDDLE EAST) FZE")[0]
    assert not parties_equal("APRIL FAR EAST (M) SDN BHD", "APRIL FINE PAPER TRADING")[0]


def test_ports_align_by_meaning_not_formatting():
    assert ports_equal("PORT KLANG (WESTPORT), MALAYSIA (MYPKG)", "Port Klang, Malaysia")[0]
    assert ports_equal("SINGAPORE (SGSIN)", "SINGAPORE")[0]
    assert ports_equal("HOCHIMINH CITY, VIETNAM (VNSGN)", "HO CHI MINH CITY, VIETNAM")[0]


def test_ports_detect_real_differences_even_with_same_code():
    assert not ports_equal("MOMBASA, KENYA (KEMBA)", "TUTICORIN, INDIA (KEMBA)")[0]
    assert not ports_equal("SINGAPORE (SGSIN)", "PORT KLANG (WESTPORT), MALAYSIA (SGSIN)")[0]


def test_container_count_parsing():
    assert parse_container_count("6 x 40'HC") == 6
    assert parse_container_count("15 x 20'GP") == 15
    assert parse_container_count("3") == 3
    assert parse_container_count("____") is None
    assert count_equal("3 x 40'HC", "4 x 40'HC")[0] is False
    assert count_equal("3 x 40'HC", "3 x 20'GP")[0] is True


def test_weight_parsing_and_units():
    assert parse_weight_kg("131,058 KG") == 131058
    assert parse_weight_kg("243588") == 243588
    assert parse_weight_kg("138 MT") == 138000
    assert parse_weight_kg("____MT") is None
    assert weight_equal("22,000 KG", "22000")[0] is True
    assert weight_equal("21,114 KG", "23,114 KG")[0] is False


def test_placeholders():
    for v in ("", "   ", "???", "_______ MTS", "TBA", "N/A", "____MT", "-"):
        assert is_placeholder(v), v
    assert not is_placeholder("KARACHI, PAKISTAN")


def test_compare_fields_reports_only_real_mismatches():
    si = {
        "shipper": fv("APRIL FAR EAST (M) SDN BHD"), "consignee": fv("EAST BRIGHT FZ-LLC"), "notify_party": fv("EAST BRIGHT FZ-LLC"),
        "port_of_loading": fv("NANTONG, CHINA (CNNTG)"), "port_of_discharge": fv("KARACHI, PAKISTAN (PKKHI)"),
        "container_count": fv("3"), "gross_weight_kg": fv("22000"),
    }
    bl = dict(si)
    bl["container_count"] = fv("4")
    rows, defects = compare_fields(si, bl)
    assert defects == ["container_count"]
    row = next(r for r in rows if r.field == "container_count")
    assert row.si_value == "3" and row.bl_value == "4" and row.match is False


def test_missing_value_is_not_a_defect():
    si = {"shipper": fv("A"), "consignee": FieldValue(value=None, evidence="CONSIGNEE: ")}
    bl = {"shipper": fv("A"), "consignee": fv("B")}
    rows, defects = compare_fields(si, bl)
    assert defects == []
    assert next(r for r in rows if r.field == "consignee").match is None
