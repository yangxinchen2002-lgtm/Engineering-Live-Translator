from copy import deepcopy
from tools.live_checks import verify_results


def results():
    return {
        "C": {"exit_code": 0, "pause_requested_ns": 0, "resume_requested_ns": 4_000_000_000,
              "diagnostics": [{"samples": 16000, "rms": 0.1, "monotonic_ns": 1_000_000_000},
                              {"samples": 32000, "rms": (160 / 32000) ** 0.5, "monotonic_ns": 3_000_000_000},
                              {"samples": 48000, "rms": (320 / 48000) ** 0.5, "monotonic_ns": 6_000_000_000}]},
        "D": {"exit_code": 1, "errors": [{"error": "target_exited"}]},
        "E": {"exit_code": 0, "summaries": [{"complete": True, "signal_detected": True}] * 10},
        "A_B": {"exit_code": 0, "summaries": [{"isolation_pass": True, "audio_seconds": 599.95}]},
    }


def test_acceptance_requires_actual_pause_and_resume():
    r = results()
    assert all(verify_results(r, 600).values())
    r["C"]["diagnostics"][-1]["rms"] = (160 / 48000) ** 0.5
    assert not verify_results(r, 600)["C"]


def test_successful_exit_alone_does_not_mean_acceptance():
    r = results()
    r["C"]["diagnostics"] = []
    r["E"]["summaries"] = r["E"]["summaries"][:9]
    r["A_B"]["summaries"][-1]["audio_seconds"] = 5
    checks = verify_results(r, 600)
    assert not checks["C"] and not checks["E"] and not checks["A_B"]
