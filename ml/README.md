# VERIFEX model card and reproduction

## Data and permissions

The shipped Compact U-Net was trained on 1,000 fictional original/tampered pairs, for 2,000 classification images. Each pair has a binary tamper mask. The generator creates 20 layout families, varying fonts, page orientation, decoration, fields, and backgrounds. It applies field replacement, erasure, copy-move, local blur, local compression, and simulated scan patches. The prepared set contains 1,400 train, 300 validation, and 300 test images with equal class counts within each split. Entire layouts and original pairs stay in one split. Pixel masks follow geometric preprocessing and training augmentations. Exact duplicate images are excluded by decoded-pixel hash.

| Source | Access and format | Use |
| --- | --- | --- |
| [Kriyam TamperFlow](https://huggingface.co/datasets/kriyam-ai/kriyam-tamperflow) | Public, CC BY-NC 4.0, attribution required. 2,307 PNG rows with genuine/altered labels, polygon regions, and C0/C2/C4 compression tiers. Source revision is pinned in the downloader. | External evaluation only. Images and annotations stay local. |
| [DocTamper project](https://github.com/qcf-568/DocTamper), [CVPR paper](https://openaccess.thecvf.com/content/CVPR2023/html/Qu_Towards_Robust_Tampered_Text_Detection_in_Document_Image_New_Dataset_CVPR_2023_paper.html) | The authors report 170,000 tampered images with pixel labels in LMDB. Non-commercial university and research use requires approval and archive credentials. | No files downloaded. Apply through the official repository with an eligible university contact, then use the provided LMDB viewer. Genuine negatives require separately permitted data such as the authors’ TFR source. |
| [FUNSD](https://guillaumejaume.github.io/FUNSD/download/), [CORD](https://github.com/clovaai/cord) | Forms and receipts for document understanding. FUNSD has 199 annotated forms. CORD supplies receipt OCR and layout annotations under CC BY 4.0. | No forgery labels. Excluded from training and metrics. |

The source review checked Hugging Face and DocTamper’s official Kaggle distribution information. The Roboflow Universe and Papers With Code listings did not provide a verified dataset and license for this run. TamperFlow publishes 700 altered and 69 genuine images per tier. The recorded evaluation downloaded and verified eight of each from C0. Some published file URLs returned HTTP 404, so the downloader skipped those IDs and recorded the selected files. [Public sample manifest](results/public-dataset-manifest.jsonl), [download summary](results/public-dataset-summary.json).

## Reproduce

Install the [base backend dependencies](../README.md), then from the repository root:

~~~powershell
python -m pip install -r ml/requirements.txt
python -m ml.scripts.generate_synthetic_data --pairs 1000 --seed 427
python -m ml.scripts.prepare_dataset --size 128
python -m ml.training.train_segmenter --epochs 16 --batch 24 --lr 0.002 --threads 5 --seed 427
python -m ml.training.train_classifier --architecture ocr_forest --threads 4
python -m ml.training.train_classifier --architecture resnet18 --epochs 15 --batch 32 --threads 4
python -m ml.training.evaluate_model --select-threshold
python -m ml.inference.predict ml/results/failure.png --out .verifex/model-outputs
~~~

Add **--ocr** to the Random Forest command to use PaddleOCR line boxes. The recorded forest experiment used OpenCV text regions. Training uses CUDA when the installed PyTorch build exposes it and otherwise runs on CPU. Fonts can differ across operating systems. The manifest and checkpoint hashes identify the recorded run.

For Google Colab, select a GPU runtime, clone this repository, change the notebook directory to the checkout, and run:

~~~python
!pip install -r backend/requirements.txt -r ml/requirements.txt
!python -m ml.scripts.generate_synthetic_data --pairs 1000 --seed 427
!python -m ml.scripts.prepare_dataset --size 128
!python -m ml.training.train_segmenter --epochs 16 --batch 24 --threads 4
!python -m ml.training.evaluate_model --select-threshold
~~~

To acquire an academic-use external sample after reviewing the dataset card:

~~~powershell
python -m ml.scripts.download_datasets --accept-noncommercial --per-class 8 --tiers C0
python -m ml.training.evaluate_model --public ml/datasets/raw/tamperflow
~~~

## Evaluation and interpretation

See [recorded metrics](results/metrics.json), [confusion matrix](results/confusion_matrix.png), [training curves](results/training_curves.png), and [precision–recall curve](results/precision_recall.png). Checkpoint selection used validation F1 and pixel Dice during training. The deployed image threshold was selected on validation by balanced accuracy, with lower false-positive rate as the tie-breaker. Test examples were reserved for evaluation. The API checks the checkpoint digest before serving its recorded metrics.

The shipped model measured **57.0% accuracy, 63.6% precision, 32.7% recall, 0.432 F1, 0.581 ROC-AUC, and 0.141 pixel Dice** on 300 images from three unseen fictional layout families. It missed 101 of 150 altered images and flagged 28 of 150 genuine images. Localized regions can miss subtle edits or highlight printing and scanning artifacts. Scores are uncalibrated. The deterministic issuer and signature checks run independently.

Compact U-Net had the strongest validation balanced accuracy of the three candidates and was the only candidate with a learned mask. On the synthetic test set, ResNet18 measured 50.3% accuracy and 33.3% false positives. The text-region forest measured 51.0% accuracy and 79.3% false positives. Its higher recall came with a large increase in false alarms.

On the separate 16-image TamperFlow C0 sample, the U-Net measured **50.0% accuracy and 12.5% recall**, detecting one of eight altered images. This is an exploratory class-balanced sample of official-document images. It shows poor transfer from the synthetic certificates in this run and cannot estimate full-benchmark performance. [Kriyam TamperFlow dataset card](https://huggingface.co/datasets/kriyam-ai/kriyam-tamperflow).

The [bundled synthetic sample manifest](samples/manifest.jsonl) identifies three original/altered pairs and their masks. Regenerate the full synthetic dataset with the commands above. Public benchmark images are excluded from the repository.
