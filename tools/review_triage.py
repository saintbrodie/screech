"""Build an offline review page and promote explicitly verified human labels."""
from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from typing import Any


def promote_labels(
    manifest: list[dict[str, Any]], labels: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    sources = {item["name"]: item for item in manifest}
    if len(sources) != len(manifest):
        raise ValueError("Duplicate source names in triage manifest")
    promoted = []
    seen = set()
    for label in labels:
        name = label.get("name")
        if not isinstance(name, str) or name not in sources or name in seen:
            raise ValueError(f"Unknown or duplicate clip label: {name!r}")
        seen.add(name)
        if label.get("verified") is not True:
            raise ValueError(f"{name}: watch the full clip and explicitly verify the label")
        count = label.get("expected_count")
        if count is not None and (type(count) is not int or count < 0):
            raise ValueError(f"{name}: expected_count must be a nonnegative integer or null")
        kind = label.get("kind")
        if kind not in {"homogeneous", "transition", "hard_case"}:
            raise ValueError(f"{name}: invalid review kind")
        if kind == "homogeneous" and count is None:
            raise ValueError(f"{name}: homogeneous clips require a count")
        if kind != "homogeneous" and count is not None:
            raise ValueError(f"{name}: changing or uncertain counts must remain unlabeled")
        source = sources[name]
        if source.get("enabled", True) is False:
            raise ValueError(f"{name}: source is disabled")
        start, end = float(source["start"]), float(source["end"])
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError(f"{name}: invalid source interval")
        promoted.append({
            "name": name, "url": source["url"], "start": start, "end": end,
            "expected_count": count, "review_kind": kind,
            "source_video_id": source.get("source_video_id"),
            "label_source": "human", "verified": True,
            "notes": str(label.get("notes") or ""),
        })
    if not promoted:
        raise ValueError("No verified labels supplied")
    return promoted


def build_review(results: list[dict[str, Any]], clips_dir: Path) -> str:
    cards = []
    for result in results:
        clip = str(result["clip"])
        if Path(clip).name != clip:
            raise ValueError(f"Invalid clip filename: {clip}")
        name = Path(clip).stem
        if result.get("category") == "unreadable":
            cards.append(f'<article><h2>{html.escape(clip)}</h2><p>Unavailable for labeling: '
                         f'{html.escape(str(result.get("error", "unreadable")))}</p></article>')
            continue
        video = (clips_dir / clip).resolve().as_uri()
        preview = result.get("preview")
        poster = f' poster="{html.escape(Path(preview).resolve().as_uri(), quote=True)}"' if preview else ""
        cards.append(f'''<article data-name="{html.escape(name, quote=True)}">
<h2>{html.escape(clip)}</h2><p>Search suggestion: {html.escape(str(result.get("category", "unknown")))}</p>
<video controls preload="none" src="{html.escape(video, quote=True)}"{poster}></video>
<p>Source range: {html.escape(str(result.get("source_start")))}–{html.escape(str(result.get("source_end")))} seconds</p>
<label>Review kind <select class="kind"><option value="homogeneous">Constant count</option><option value="transition">Count changes</option><option value="hard_case">Count uncertain / hard case</option></select></label>
<label>Bird count <input class="count" type="number" min="0" step="1" placeholder="Human count"></label>
<label>Notes <textarea class="notes" placeholder="Resting, moving, occlusion, lighting, false positives…"></textarea></label>
<label><input class="verified" type="checkbox"> I watched the full clip and verified this label</label>
</article>''')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><title>SCREECH archive review</title>
<style>body{font:16px system-ui;background:#101923;color:#edf3f7;max-width:1000px;margin:30px auto;padding:20px}article{border:1px solid #637787;padding:20px;margin:24px 0}video{width:100%;max-height:500px}label{display:block;margin:12px 0}input,select,textarea,button{font:inherit;padding:8px}textarea{width:95%}button{cursor:pointer}h2{overflow-wrap:anywhere}#status{color:#ffc96b}</style>
<h1>SCREECH archive review</h1><p>Detector categories and annotated posters are search aids. Play each full clip before labeling. Leave uncertain counts blank. Only checked reviews are exported. This page stays on your computer; save labels before closing it.</p>
<button id="export">Download verified labels</button><p id="status" role="status"></p>
''' + "\n".join(cards) + '''<script>
document.querySelectorAll('.kind').forEach(select=>select.addEventListener('change',()=>{
 const count=select.closest('article').querySelector('.count');
 count.disabled=select.value!=='homogeneous'; if(count.disabled) count.value='';
}));
document.querySelector('#export').addEventListener('click',()=>{
 const labels=[]; const status=document.querySelector('#status');
 for(const card of document.querySelectorAll('article[data-name]')){
  if(!card.querySelector('.verified').checked) continue;
  const kind=card.querySelector('.kind').value, raw=card.querySelector('.count').value;
  const count=kind==='homogeneous' && raw!=='' ? Number(raw) : null;
  if(kind==='homogeneous' && (count===null || !Number.isInteger(count) || count<0)){
   status.textContent='Enter a constant count for '+card.dataset.name; return;
  }
  labels.push({name:card.dataset.name,kind,expected_count:count,verified:true,notes:card.querySelector('.notes').value});
 }
 if(!labels.length){status.textContent='Verify at least one review first.';return;}
 const url=URL.createObjectURL(new Blob([JSON.stringify(labels,null,2)],{type:'application/json'}));
 const link=document.createElement('a');link.href=url;link.download='triage-labels.json';link.click();
 setTimeout(()=>URL.revokeObjectURL(url),1000);status.textContent='Exported '+labels.length+' verified reviews.';
});
</script></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    review = sub.add_parser("build")
    review.add_argument("--results", type=Path, default=Path("tests/fixtures/triage-results.json"))
    review.add_argument("--clips-dir", type=Path, default=Path("tests/fixtures/triage"))
    review.add_argument("--output", type=Path, default=Path("tests/fixtures/triage-review.html"))
    promote = sub.add_parser("promote")
    promote.add_argument("--manifest", type=Path, default=Path("tests/fixtures/triage.json"))
    promote.add_argument("--labels", type=Path, required=True)
    promote.add_argument("--output", type=Path, default=Path("tests/fixtures/clips.json"))
    args = parser.parse_args()
    if args.command == "build":
        results = json.loads(args.results.read_text(encoding="utf-8"))
        if not results:
            raise SystemExit("No triage results to review")
        content = build_review(results, args.clips_dir)
    else:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        labels = json.loads(args.labels.read_text(encoding="utf-8"))
        promoted = promote_labels(manifest, labels)
        existing = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else []
        by_name = {item["name"]: item for item in existing}
        by_name.update({item["name"]: item for item in promoted})
        content = json.dumps(list(by_name.values()), indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    print(f"Wrote {args.output.resolve()}")


if __name__ == "__main__":
    main()
