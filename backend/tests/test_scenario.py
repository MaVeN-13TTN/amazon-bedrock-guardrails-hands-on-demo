"""The bulletin_facts drift guard.

The Landing_Page presents collection and payment facts to a member as though read
from Extension Bulletin 14. These tests pin the guard that stops the two drifting
apart, because a Landing_Page stating something the bulletin does not is worse
than a page that fails to load.
"""
import pytest

from app import scenario
from app.scenario import check_bulletin_facts
from app.schemas import BulletinFacts, SectionText

BULLETIN = (
    "Collection points at Kangema and Kiriaini open from 06:00 to 10:00 on "
    "Tuesdays and Fridays only. Members must present a valid member number at "
    "the gate.\n\nPayment for delivered produce is released fourteen days after "
    "grading is complete. Grading results are posted at the collection point.\n"
)

FACTS = {
    "collection_points": ["Kangema", "Kiriaini"],
    "collection_opens": "06:00",
    "collection_closes": "10:00",
    "collection_days": ["Tuesday", "Friday"],
    "gate_requirement": "present a valid member number at the gate",
    "payment_delay_days": 14,
    "payment_release": "released fourteen days after grading is complete",
    "payment_note": "Grading results are posted at the collection point.",
}


def test_matching_facts_pass():
    check_bulletin_facts(FACTS, BULLETIN)


def test_committed_scenario_passes_its_own_guard():
    """The shipped scenario.json must satisfy the guard, or nothing imports."""
    check_bulletin_facts(
        {
            "collection_points": scenario.BULLETIN_FACTS.collection_points,
            "gate_requirement": scenario.BULLETIN_FACTS.gate_requirement,
            "payment_release": scenario.BULLETIN_FACTS.payment_release,
            "payment_note": scenario.BULLETIN_FACTS.payment_note,
        },
        scenario.EXTENSION_BULLETIN,
    )


def test_drifted_scalar_is_rejected_and_named():
    """A collection window edited in the facts but not the bulletin must fail."""
    drifted = {**FACTS, "collection_opens": "05:00"}
    with pytest.raises(ValueError) as exc:
        check_bulletin_facts(drifted, BULLETIN)
    message = str(exc.value)
    assert "bulletin_facts.collection_opens" in message
    assert "05:00" in message


def test_drifted_list_element_is_named_with_its_index():
    """A renamed collection point must name which element drifted."""
    drifted = {**FACTS, "collection_points": ["Kangema", "Kangari"]}
    with pytest.raises(ValueError) as exc:
        check_bulletin_facts(drifted, BULLETIN)
    assert "bulletin_facts.collection_points[1]" in str(exc.value)


def test_every_drifted_field_is_reported_not_just_the_first():
    """A bulletin rewrite breaks several facts at once; all should be named."""
    drifted = {**FACTS, "collection_opens": "05:00", "collection_closes": "18:00"}
    with pytest.raises(ValueError) as exc:
        check_bulletin_facts(drifted, BULLETIN)
    message = str(exc.value)
    assert "collection_opens" in message and "collection_closes" in message


def test_integer_facts_are_not_stringified():
    """payment_delay_days is 14 while the bulletin says "fourteen".

    Stringifying non-strings would make the guard reject a correct scenario.
    """
    assert "14" not in BULLETIN
    check_bulletin_facts({"payment_delay_days": 14}, BULLETIN)


def test_models_reject_a_missing_field():
    with pytest.raises(ValueError):
        BulletinFacts.model_validate({k: v for k, v in FACTS.items() if k != "payment_note"})
    with pytest.raises(ValueError):
        SectionText.model_validate({"title": "no body"})
