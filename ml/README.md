# VERIFEX model card and training

VERIFEX uses one Balanced U-Net checkpoint, `mixed-unet-v3`. It scores visual evidence of edits and produces a localization mask for each page. The checkpoint takes 320 × 320 RGB inputs with a grayscale residual channel. Issuance and signature verification run separately.

## Data and results

| Source | Training pool | Held-out test | Test result |
| --- | ---: | ---: | --- |
| [AIForge-Doc v2](https://huggingface.co/datasets/Scam-AI/AIForge-Doc-v2) | 4,166 | 1,225 | ROC-AUC 0.502 |
| [Kriyam TamperFlow](https://huggingface.co/datasets/kriyam-ai/kriyam-tamperflow) | 1,026 | 338 | ROC-AUC 0.909 |
| [DocTamper](https://github.com/qcf-568/DocTamper) | 5,899 | 1,196 | Recall 43.7% |
| VERIFEX synthetic certificates | 1,400 | 300 | ROC-AUC 0.833, F1 0.753 |

The run also used 5,586 matched crop views from the training pool. AIForge reserves its official test split and keeps matched genuine and edited pages together. TamperFlow keeps each document's C0, C2, and C4 compression views in the same split. DocTamper provides sampled LMDB pages for pixel supervision. Its test split contains altered pages only. Synthetic layouts stay together by template family. Dataset access and redistribution follow the respective source terms.

AIForge performance is near chance, and the selected threshold flagged 68.6% of genuine AIForge pages and 45.5% of genuine TamperFlow pages. The model score is a review signal. See [per-dataset metrics](results/metrics.json), the [confusion matrix](results/confusion_matrix.png), the [training loss](results/training_curves.png), and the [precision–recall curve](results/precision_recall.png). The API serves recorded metrics when the checkpoint digest and classification threshold match.

## Document verdict classifier

The app uses a separate classifier over the U-Net's page features, localization map, and scan statistics. The selected classifier uses gradient-boosted trees. It was fitted on 2,111 training pages, with selection on 2,239 validation pages. Each upload is scored from its own pages. An exact signed match can independently confirm the registered version.

| Metric on 3,059 reserved pages | U-Net cutoff | Verdict classifier |
| --- | ---: | ---: |
| Genuine pages incorrectly flagged | 55.2% | 38.6% |
| Altered pages detected | 58.6% | 50.7% |
| Balanced accuracy | 51.7% | 56.0% |
| ROC-AUC | 0.526 | 0.568 |

The real-world accuracy of the verdict depends on document type and capture quality. AIForge remains near chance at ROC-AUC 0.500. The displayed visual confidence describes distance from the decision threshold. Per-source results are stored in [the verdict classifier artifact](models/document_assessment.json).

## Train and evaluate

Install the [backend dependencies](../README.md) and the ML requirements. Obtain the full AIForge archive with authentic pairs, a TamperFlow snapshot with `metadata.jsonl`, and the approved DocTamper LMDB files. Set `$aiForgeRoot`, `$tamperFlowRoot`, and `$docTamperRoot` to the respective extracted directories before running these commands from the repository root.

~~~powershell
python -m pip install -r ml/requirements.txt lmdb
python -m ml.scripts.generate_synthetic_data --pairs 1000 --seed 427
$run = '.verifex/balanced-training'
$data = Join-Path $run 'data-320'
$crops = Join-Path $run 'crops-320'
$model = Join-Path $run 'candidate'
python -m ml.scripts.prepare_mixed --aiforge $aiForgeRoot --tamperflow $tamperFlowRoot --doctamper $docTamperRoot --synthetic ml/datasets/synthetic --out $data --size 320
python -m ml.scripts.prepare_paired_crops --data $data --aiforge $aiForgeRoot --synthetic ml/datasets/synthetic --out $crops --size 320
$env:CUBLAS_WORKSPACE_CONFIG = ':4096:8'
python -m ml.training.train_balanced --data $data --paired-crops $crops --out $model --batch 16 --epochs 10 --lr 0.001 --steps 180 --amp
python -m ml.training.evaluate_model --data $data --model $model --out (Join-Path $run 'results')
python -m ml.training.fit_assessment --data $data --model $model --out (Join-Path $model 'document_assessment.json')
~~~

This recipe trains a fresh checkpoint. The recorded run used a lower-resolution warm-up before fine-tuning at 320 pixels. The training script supports initialization from a compatible Balanced U-Net with `--init`. Threshold selection uses validation pages, and the evaluator measures the resulting checkpoint on the held-out test split. To test blending the same model's page and pixel scores, use `ml.training.calibrate_balanced` and evaluate its output with the same evaluator.

Use the shipped checkpoint from the command line with `python -m ml.inference.predict path/to/document.pdf`. Add `--out .verifex/model-outputs` to save the per-page heatmaps and masks.
