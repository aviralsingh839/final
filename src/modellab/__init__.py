"""CHRONO Model Lab — controlled automated model training (V8.2).

RESEARCH-ONLY package.  The Model Lab automates the *engineering* workflow
(dataset intake → inspection → validation → patient-level splitting →
training → evaluation → comparison → registry) while keeping *deployment*
under explicit human control:

    AUTOMATED TRAINING  ≠  UNCONTROLLED SELF-TRAINING

Hard rules enforced across the package:

* Nothing inside an uploaded dataset ZIP is ever executed.
* Training refuses to start while critical validation checks fail.
* Splits are patient-level whenever patient identifiers exist.
* No metric is ever fabricated — missing results render as
  "NOT YET EVALUATED" / "INSUFFICIENT DATA".
* A trained model NEVER becomes the active model without a human pressing
  APPROVE; the previous approved model stays available for rollback.
* Patient-facing and clinician-facing dashboards cannot trigger training.
"""

RESEARCH_ONLY_NOTICE = (
    "Research and development tool. Model outputs are not medical diagnoses. "
    "Controlled automated model training: the system automates the engineering "
    "workflow; a human researcher controls dataset, experiment, evaluation, "
    "approval and deployment."
)
