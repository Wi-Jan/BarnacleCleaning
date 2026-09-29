"""
Train YOLOv8 on the barnacle dataset.

Usage:
    python train.py                        # defaults: yolov8s, 100 epochs, 960px
    python train.py --model yolov8m.pt     # bigger model for max accuracy
    python train.py --epochs 200           # more training
"""

import argparse
from pathlib import Path
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent
DATA_YAML = ROOT / "barnacles_dataset" / "data.yaml"
RUNS_DIR = ROOT / "runs"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--model", default="yolov8s.pt")
    ap.add_argument("--name", default="barnacle_detect")
    args = ap.parse_args()

    model = YOLO(args.model)
    model.train(
        data=str(DATA_YAML),
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        project=str(RUNS_DIR),
        name=args.name,
        exist_ok=True,
        patience=25,
        verbose=True,
        # Stronger augmentation for small/dense objects
        mosaic=1.0,
        mixup=0.15,
        copy_paste=0.3,
        hsv_h=0.015, hsv_s=0.7, hsv_v=0.4,
        degrees=10.0,
        translate=0.1,
        scale=0.5,
        fliplr=0.5,
        flipud=0.1,
        # Optimizer
        optimizer="auto",
        lr0=0.01,
        cos_lr=True,
        # Detection tuning
        box=7.5,
        cls=0.5,
        dfl=1.5,
    )

    best = RUNS_DIR / args.name / "weights" / "best.pt"
    print(f"\nTraining complete! Best model saved at:\n  {best}")

if __name__ == "__main__":
    main()
