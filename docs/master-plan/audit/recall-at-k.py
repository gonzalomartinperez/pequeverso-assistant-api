import sys

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

from app.ai.evidence import passages, rank
from scripts import evaluate_corpus as ec

cases = ec.load()
items = passages(ec.conv.CATALOG)
print(len(items), "passages")
rows = []
for c in cases:
    rel = c["expect"].get("retrieval")
    if not rel:
        continue
    ranked = [p.id for p, s in rank(ec._query(c), items) if s > 0]
    pos = [ranked.index(r) + 1 for r in rel if r in ranked]
    rows.append((c["family"], c["expect"]["language"], min(pos) if pos else None))


def rk(rs, k):
    return round(sum(1 for *_, b in rs if b and b <= k) / len(rs), 3) if rs else None


for k in (1, 3, 5, 10):
    print("overall", k, rk(rows, k), len(rows))
fams = sorted({r[0] for r in rows})
for f in fams:
    rs = [r for r in rows if r[0] == f]
    print(f, len(rs), [rk(rs, k) for k in (1, 3, 5, 10)])
for l in ("es", "en", "unsupported"):
    rs = [r for r in rows if r[1] == l]
    print(l, len(rs), [rk(rs, k) for k in (1, 3, 5, 10)])
