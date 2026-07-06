"""Regression tests for client-profile injection (multi-tenant correctness).

These pin two bugs found after the client-data extraction refactor:
- the injected profile must reach OCR worker threads (contextvars do not
  propagate into a ThreadPoolExecutor by default);
- the OCR VAT signal must still recognise the profile's bare SIRENs.
"""
import contextvars
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from controldone.profile import current_profile, load_profile, use_profile

_ACME = Path(__file__).parent / "fixtures" / "acme"


def test_profile_propagates_into_threadpool_workers():
    # ocr.extract_text_per_page fans pages out over a ThreadPoolExecutor; the
    # profile injected on the main thread must reach the workers.
    acme = load_profile(client_dir=_ACME)
    with use_profile(acme):
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut = pool.submit(contextvars.copy_context().run,
                              lambda: current_profile().name)
            assert fut.result() == acme.name


def test_sig_vat_includes_profile_sirens():
    from controldone.ocr import _sig_vat
    acme = load_profile(client_dir=_ACME)
    with use_profile(acme):
        pat = _sig_vat()
        # bare SIRENs of the profile are recognised (OCR keeps the 9 digits
        # even when it mangles the FR key)
        assert pat.search("000000001")
        assert pat.search("000000002")
        # a full French VAT still matches via the generic pattern
        assert pat.search("FR12345678901")
        # a foreign number that is neither matches nothing
        assert not pat.search("987654321")
