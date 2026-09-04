from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import cv2


DEFAULT_PROMPTS = {
    "empty": "an empty red-shouldered hawk nest with no birds present",
    "resting": "a red-shouldered hawk sitting still or resting in its nest",
    "active": "a red-shouldered hawk actively moving around in its nest",
    "multiple": "two red-shouldered hawks together in the nest",
}


def parse_prompt(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("prompts must use LABEL=TEXT")
    label, text = value.split("=", 1)
    label = label.strip()
    text = text.strip()
    if not label or not text:
        raise argparse.ArgumentTypeError("prompts must use non-empty LABEL=TEXT")
    return label, text


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Experimental zero-shot CLIP probe for archived Hawk Cam clips. "
            "This is an evaluation tool, not part of the live Screech hot path."
        )
    )
    parser.add_argument("clip", type=Path)
    parser.add_argument("--sample-seconds", type=float, default=2.0)
    parser.add_argument("--model", default="ViT-B-32")
    parser.add_argument("--pretrained", default="laion2b_s34b_b79k")
    parser.add_argument("--device", default="auto")
    parser.add_argument(
        "--prompt",
        action="append",
        type=parse_prompt,
        help="Override prompts with LABEL=TEXT. Repeat for multiple labels.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tests/fixtures/clip-behavior-results.json"),
    )
    args = parser.parse_args()

    try:
        import open_clip
        import torch
        from PIL import Image
    except ImportError as exc:
        raise SystemExit(
            "CLIP extras are not installed. Run: uv sync --extra clip"
        ) from exc

    device = args.device
    if device == "auto":
        if torch.cuda.is_available():
            device = "cuda"
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"

    prompts = dict(args.prompt) if args.prompt else DEFAULT_PROMPTS
    labels = list(prompts)
    texts = [prompts[label] for label in labels]

    print(f"Loading OpenCLIP {args.model} / {args.pretrained} on {device}...")
    model, _, preprocess = open_clip.create_model_and_transforms(
        args.model,
        pretrained=args.pretrained,
        device=device,
    )
    tokenizer = open_clip.get_tokenizer(args.model)

    with torch.no_grad():
        text_tokens = tokenizer(texts).to(device)
        text_features = model.encode_text(text_tokens)
        text_features /= text_features.norm(dim=-1, keepdim=True)

    capture = cv2.VideoCapture(str(args.clip))
    if not capture.isOpened():
        raise SystemExit(f"Could not open {args.clip}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    sample_frames = max(1, int(round(fps * args.sample_seconds)))
    frame_index = 0
    samples = []

    while True:
        ok, frame = capture.read()
        if not ok:
            break

        if frame_index % sample_frames == 0:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = preprocess(Image.fromarray(rgb)).unsqueeze(0).to(device)
            with torch.no_grad():
                image_features = model.encode_image(image)
                image_features /= image_features.norm(dim=-1, keepdim=True)
                probabilities = (100.0 * image_features @ text_features.T).softmax(dim=-1)[0]

            scores = {
                label: round(float(probabilities[index].cpu().item()), 5)
                for index, label in enumerate(labels)
            }
            winner = max(scores, key=scores.get)
            samples.append(
                {
                    "timestamp_seconds": round(frame_index / fps, 3),
                    "winner": winner,
                    "scores": scores,
                }
            )

        frame_index += 1

    capture.release()

    aggregate = {}
    for label in labels:
        aggregate[label] = round(
            statistics.fmean(sample["scores"][label] for sample in samples), 5
            if samples
            else 0.0,
            5,
        )

    output = {
        "clip": str(args.clip),
        "model": args.model,
        "pretrained": args.pretrained,
        "device": device,
        "prompts": prompts,
        "aggregate_mean_scores": aggregate,
        "samples": samples,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print("Aggregate mean prompt scores:")
    for label, score in sorted(aggregate.items(), key=lambda item: item[1], reverse=True):
        print(f"  {label:<12} {score:.3f}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
