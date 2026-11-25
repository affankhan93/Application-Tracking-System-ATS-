import csv 
import pathlib
import statistics
import sys 

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.integrity import scan
from core.parser import parse_resume
from core.scoring import score_resume

D = ROOT / 'data' / 'sample_resumes'
rows = list(csv.DictReader(open(D / 'labels.csv', encoding='utf-8')))
data = {r['filename']: (D / r['filename']).read_bytes() for r in rows}
parsed = {f: parse_resume(b, f) for f, b in data.items()}
reports = {f: scan(parsed[f], data[f], use_ocr=True)for f in data}

print("Clean resumes (visible text)")
good, weak, role_ok, clean = {}, {}, 0, 0
for r in rows:
    if r['is_poisoned'] == 'True':
        continue
    s = score_resume(parsed[r['filename']], reports[r['filename']].visible_text)
    (good if r['quality'] == 'good' else weak)[r['field']] = s['total']
    role_ok += s['role_used'] == r['field']
    clean += 1
    print(f"{r['filename']:<14}{r['field']:<28}{r['quality']:<6}{s['total']:>4} {s['band']}")
pairs_ok = sum(good[f] > weak[f] for f in good)
print(f"mean good {statistics.mean(good.values()):.1f} | mean weak {statistics.mean(weak.values()):.1f} | "
      f"good beats weak in {pairs_ok}/{len(good)} fields | role detected correctly {role_ok}/{clean}")

print("\n Poisoned resumes: score on the full file text vs the visible text")
for r in rows:
    if r['is_poisoned'] != 'True':
        continue
    f = r['filename']
    full = score_resume(parsed[f], parsed[f].text)['total']
    vis = score_resume(parsed[f], reports[f].visible_text)['total']
    print(f"{f:<14}{r['poison_type']:<34}full text {full:>3} | visible text {vis:>3}")

print("\n*job description match (Data Scientist JD)*")
JD = ("We are hiring a Data Scientist. Requirements: Python, pandas, scikit-learn, SQL, statistics, machine learning, "
      "feature engineering, A/B testing and data visualization. Experience building and deploying predictive models; "
      "XGBoost preferred.")

for f, label in (('resume_01.pdf', 'DS good'), ('resume_10.pdf', 'DS weak'), ('resume_08.pdf', 'Accountant good')):
    s = score_resume(parsed[f], reports[f].visible_text, job_description=JD)
    jd = s['jd']
    print(f"{label:<16}score {s['total']:>3} | keyword {s['components']['keyword_match']['score']:>4} | "
          f"similarity {jd['similarity']} ({jd['method']}) | missing from JD: {jd['missing_jd_skills']}")
    