"""Run all five missions in order (M1 -> M5)."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from missions import m1_efficiency_audit, m2_inference_levers, m3_purchasing, m4_allocation, m5_report


def main():
    for m in (m1_efficiency_audit, m2_inference_levers, m3_purchasing, m4_allocation):
        m.run(verbose=True)
        print()
    m5_report.run(verbose=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
