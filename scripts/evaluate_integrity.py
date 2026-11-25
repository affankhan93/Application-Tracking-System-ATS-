"""Measure the integrity scan on data/sample_resumes (uses labels.csv)."""

import csv 
import pathlib
import sys 

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.integrity import scan
from core.parser import parse_resume

D = ROOT / 'data' / 'sample_resumes'
tp = fp = fn = tn = 0 
print(f"{'file':<16}{'poison type':<34}{'risk':<11} flags")
for r in csv.DictReader(open(D / 'labels.csv', encoding = 'utf-8')):
    data = (D / r['filename']).read_bytes()
    rep = scan(parse_resume(data, r['filename']), data)
    flagged, poisoned = rep.risk != 'clean', r['is_poisoned'] == 'True'
    tp += poisoned and flagged         # true poisitve 
    fn += poisoned and not flagged     # false negative
    fp += (not poisoned) and flagged     # false positive 
    tn += (not poisoned) and not flagged  # true negative 
    print(f"{r['filename']:<16}{r['poison_type'] or '-':<34}{rep.risk:<11}{[f['flag_type']for f in rep.findings]}")

precision = tp / (tp + fp) if tp + fp else 0 
recall = tp / (tp + fn) if tp + fn else 0 
print(f"\n poisoned caught {tp}/{tp + fn} (recall {recall:.2f}) | clean wrongly flagged {fp}/{fp + tn} (precision {precision:.2f})")

