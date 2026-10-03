from swatplus_builder.governance.tiers import CLAIM_TIERS, tier_label, tier_rank
from swatplus_builder.workflows.contracts import negotiate_workflow


def test_public_names_preserve_identifiers_and_order():
    assert tier_label('research_grade') == 'Gate-verified'
    assert tier_label('publication_grade') == 'Calibration verified'
    assert tier_label(None) == 'Not evaluated'
    assert tier_label('blocked') == 'Blocked'
    assert tier_rank('publication_grade') < tier_rank('research_grade')
    assert 'Gate-verified' not in CLAIM_TIERS


def test_new_and_legacy_request_language_share_contract_identifier():
    for label in ('Gate-verified', 'gate verified', 'research-grade'):
        request = negotiate_workflow(f'{label} model for USGS 12054000 from 2000-01-01 to 2015-12-31')
        assert request.claim_tier == 'research_grade'
    assert negotiate_workflow('Calibration verified model').claim_tier == 'publication_grade'
