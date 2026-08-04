# PAN-C2 AI review demonstration

This package is a training fixture for reviewing a mock DO-178C/DO-331-oriented Command-and-Control panel baseline. It is not certification evidence and must not be used in operational software.

## Blind review setup

Give the reviewing AI:

- the four DCDS software standards at the suite root; and
- everything in `candidate_artifacts/`.

Keep `facilitator_only/DCDS_C2_Facilitator_Issue_Manifest.docx` hidden until scoring. It lists the seeded issues, applicable rule identifiers, suggested severity, and cross-artefact inconsistencies.

The candidate files are intentionally valid, readable artefacts with deliberate semantic and assurance defects. Several incorrect behaviours agree across requirements, model, implementation, and tests; this tests whether the reviewer checks them against the governing standards instead of mistaking internal consistency for correctness.

## Contents

- `DCDS_C2_SRATS.xlsx` — conventional System Requirements Allocated to Software register, trace matrix, and formula-based review summary. No project-specific SRATS form was supplied.
- `DCDS_C2_High_Level_Requirements.docx` — seeded high-level software requirements.
- `DCDS_C2_Low_Level_Requirements.docx` — seeded low-level requirements and design details.
- `DCDS_C2_SCADE_Model_Stub.txt` — human-readable pseudo-SCADE Suite model stub; not a native SCADE project.
- `dcds_c2_stub.h` / `dcds_c2_stub.c` — buildable C implementation stub representing generated/integration behaviour.
- `DCDS_C2_SCADE_Test_Cases.csv` — SCADE Test-style test specification and status table.
- `test_dcds_c2_stub.c` — buildable test harness containing deliberately weak and incorrect tests.

## Example test build

```sh
cc -std=c99 -Wall -Wextra -pedantic dcds_c2_stub.c test_dcds_c2_stub.c -o test_dcds_c2_stub
./test_dcds_c2_stub
```

Passing these seeded tests does not demonstrate compliance; that is one of the intended review lessons.
