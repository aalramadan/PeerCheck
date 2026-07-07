# CoCoDet

This repository contains the code for CoCoDet, an AI review detector.

> Fork from Y1hanChen/COCONUTS: https://github.com/Y1hanChen/COCONUTS

### Prerequisites
2.  **Install the required packages:**
```bash
pip install -r requirements.txt
```

#### Inference 
This script will load the `model/CoCoDet.bin` model and run predictions on the `example/input.jsonl` dataset.

```bash
python CoCoNUTS.py \
    --model_name_or_path answerdotai/ModernBERT-base \
    --trained_model_path model/CoCoDet.bin \
    --test_file example/input.jsonl \
    --output_file example/output.jsonl
```