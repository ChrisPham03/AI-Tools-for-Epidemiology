"""Parsing must keep values readable and locatable."""


def test_every_element_has_a_location(doc):
    for e in doc.elements:
        assert e.page >= 1
        assert e.bbox[2] > e.bbox[0] and e.bbox[3] > e.bbox[1]


def test_element_ids_are_unique(doc):
    ids = [e.id for e in doc.elements]
    assert len(ids) == len(set(ids))


def test_tables_found_with_rows_intact(doc):
    t1, t2, t3 = doc.get("p3-table1"), doc.get("p3-table2"), doc.get("p3-table3")
    assert t1 and t2 and t3
    assert "Total sample | (193,931) | 1204 | 06.2" in t1.content
    assert "Total | 1204 | 14 | 1.2 | 214 (17.7)" in t2.content
    assert "Not vaccinated (963) | 13 | 1.35" in t3.content


def test_two_columns_not_interleaved(doc):
    text = doc.get("p3-text4").content
    assert text.startswith("Out of the 1204 cases, 14 were fatal")


def test_ligatures_repaired_and_minus_signs_kept(doc):
    all_text = " ".join(e.content for e in doc.elements)
    assert "signifi cant" not in all_text
    assert "(2828- 1478)" in all_text  # a number's minus sign must survive cleaning


def test_figures_marked_as_unread(doc):
    fig = doc.get("p3-figure1")
    assert fig.tier == 4 and "not read" in fig.note
