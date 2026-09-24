# CHRONO MODEL LAB — CONTROLLED AUTOMATED MODEL TRAINING (V8.2)

> **AUTOMATED TRAINING ≠ UNCONTROLLED SELF-TRAINING.**
> The system automates the engineering workflow. A human researcher controls
> the dataset, the experiment, the evaluation, the approval and the
> deployment. **Automate the work — do not automate the medical decision.**

Location: **🔬 RESEARCH → Model Lab** only. The Model Lab does not appear in
the patient dashboard or the clinician dashboard, neither of which can
trigger training. Patient data never silently becomes training data.

---

## 1. Architecture

```
src/modellab/
    __init__.py        research-only notice + package rules
    safezip.py         safe ZIP validation + extraction (§ Security)
    dataset_store.py   structure detection, inspection, quality, versioning
    splitting.py       patient-level splitting + leakage gate
    trainer.py         config, preprocessing, epoch loop, checkpoints, resume
    evaluation.py      AUROC/AUPRC/sens/spec/precision/F1/confusion/
                       calibration/bootstrap-CI, model comparison
    registry.py        versions, statuses, human approval gate, rollback,
                       model cards, external validation records
    resources.py       CPU/RAM/GPU/CUDA detection + feasibility
    lab.py             ModelLab facade (dashboard counts, external validation)

src/ui/model_lab_tab.py   Research-only UI (6 sub-pages)
```

Storage (never committed to Git — `**/data/model_lab/` is ignored):

```
data/model_lab/
    datasets.json                     dataset index
    datasets/DATASET-<NAME>-NNN/      extracted data + dataset.json (report)
    registry.json                     model registry + active pointer + history
    runs/run_NNN/
        config.json    metrics.csv    training.log
        checkpoint.joblib  model.joblib  evaluation.json  model_card.md
```

## 2. Dataset workflow

`UPLOAD → INSPECT → VALIDATE → CONFIGURE → TRAIN → EVALUATE → COMPARE →
HUMAN REVIEW → APPROVE → DEPLOY`

Upload accepts a ZIP; the system safely extracts it, auto-detects the
structure, hashes it (dataset id `DATASET-<NAME>-NNN` + ZIP sha256 +
per-image sha256/average-hash), and produces the **DATASET REPORT**: images,
patients, classes, images/class, images/patient, dimensions, formats,
corrupt, duplicates (exact + near), repeated filenames, missing labels,
missing patient ids, imbalance ratio, leakage risks and warnings. Image
quality is categorized **VALID / QUESTIONABLE / INVALID** — nothing is
auto-deleted; the researcher reviews.

If the structure cannot be interpreted, the import **stops** with
`"Dataset structure could not be reliably interpreted."` plus an explanation
of exactly what is missing; nothing is kept and labels are never guessed.

## 3. Supported dataset formats

**A) labels CSV (preferred)**

```
dataset.zip
├── images/
│   ├── patient001_img01.jpg
│   ├── patient001_img02.jpg
│   └── patient002_img01.jpg
└── labels.csv
```

```csv
image,patient_id,label
patient001_img01.jpg,patient001,PCOS
patient001_img02.jpg,patient001,PCOS
patient002_img01.jpg,patient002,Normal
```

Column synonyms accepted: image/filename/file/path…, patient_id/patient/
subject…, label/class/diagnosis/target…. When `patient_id` is absent, the
`patientNNN_` filename prefix is used when present.

**B) class folders**

```
dataset.zip
├── PCOS/patient001_img01.jpg
└── Normal/patient002_img01.jpg
```

Images: .png .jpg .jpeg .bmp .tif .tiff. Two classes are required by the
current pipeline.

## 4. Leakage prevention

1. **Patient-level splitting** whenever complete patient ids exist
   (default 70/15/15% of *patients*, ratios + seed configurable). Without
   ids: image-level split + explicit warning *"Patient-level leakage cannot
   be reliably ruled out."* — never a silent claim of rigor.
2. **Pre-training gate** (training refuses to start): identical image
   content under multiple patient ids; same patient across splits; identical
   sha256 across splits; near-duplicate average-hash between train and
   val/test. Error shown: *"Potential data leakage detected."* with the
   affected records.
3. Augmentation is applied to the **training split only** and recorded;
   normalization uses fixed constants so no train statistics leak into
   val/test.
4. The test split is evaluated **once**, after training, on the best-
   validation-epoch model.
5. External validation datasets must be different registered datasets and
   are never mixed into training.

## 5. Training pipeline

START TRAINING runs: validate dataset → validate labels → leakage check →
patient-level split → preprocessing (resize → grayscale → scale →
normalize; train-only flip/brightness augmentation) → model init → epoch
loop with per-epoch validation, metric tracking (`metrics.csv`), checkpoint
per epoch, configurable **early stopping** on validation loss → candidate =
best epoch → single test-set evaluation.

Backends (deliberately small; no huge model is auto-selected):

| Key | Model | Notes |
|---|---|---|
| `baseline_linear` | Lightweight linear baseline | log-loss SGD, CPU-friendly |
| `mlp_small` | Small MLP (128 hidden units) | CPU-feasible |
| `cnn_transfer` | Transfer-learning CNN | requires PyTorch/GPU; refused gracefully otherwise: *"This training configuration may require a GPU-enabled environment."* |

Class imbalance strategy is configurable and documented (`class_weighting:
balanced` = inverse-frequency sample weights; minority images are never
blindly duplicated). Interrupted runs resume from `checkpoint.joblib`
(model + optimizer state + epoch + config + history + seed).

## 6. Evaluation

Untouched-test-set report: AUROC (with bootstrap 95% CI when n≥20), AUPRC,
sensitivity, specificity, precision, recall, F1, confusion matrix,
calibration bins. Accuracy is never reported alone. Unrun experiments show
**NOT YET EVALUATED**; tiny datasets show **INSUFFICIENT DATA**. No metric
is ever fabricated.

## 7. Registry, approval, deployment, rollback

Every registered candidate gets `CHRONO-CV-NNN` with status
**EXPERIMENT / CANDIDATE / APPROVED / REJECTED / RETIRED**, storing dataset
id + hash, architecture, hyperparameters, preprocessing, split summary,
seed, code version, train/val/test metrics and external validations.

**Human approval gate:** `APPROVE MODEL` / `REJECT MODEL` /
`KEEP CURRENT MODEL`. Only APPROVE deploys; a model without a test-set
evaluation cannot be approved; the registry never changes the active model
by itself. `ROLLBACK MODEL` returns to the previous approved version; the
complete deployment history is retained. Every approved model gets a
**model card** (purpose, dataset, patients, input, architecture, metrics,
validation strategy, intended use, *not intended for*, limitations, date,
version).

## 8. Integration with CHRONO (§37)

After approval, the clinician ultrasound module displays
`Active CV model: CHRONO-CV-NNN — APPROVED RESEARCH MODEL (not clinically
validated)` and, for images that pass the V8.1 quality gate, appends a
clearly labelled **MODEL-INFERRED** decision-support score with the model
version. Without an approved model, image-derived features remain UNKNOWN.
The clinician view only consumes the model — it cannot train or replace it.

## 9. Security

* ZIP members are validated **before** extraction: no `../` traversal, no
  absolute paths/drive letters, no symlinks, size/ratio/member-count limits
  (zip-bomb guards).
* Executables and scripts (.exe .sh .py .bat .dll .so …) cause rejection of
  the archive; unexpected-but-harmless types are skipped, never extracted.
* Only whitelisted data types are extracted (images + csv/tsv/json/txt/md).
* Nothing from an uploaded archive is ever executed or imported.

## 10. Medical safety

The Model Lab displays permanently: *"Research and development tool. Model
outputs are not medical diagnoses."* Deployed models are labelled
**APPROVED RESEARCH MODEL — not clinically validated**. There is no
autonomous diagnosis, no treatment automation, no self-labeling, no
training on model predictions, and no pathway from patient dashboards into
training. The multimodal ablation (Model A–E) remains honestly **PENDING**
until a suitable labelled longitudinal dataset exists.
