"""Approach Book(사양·제원) + 10월 정가표(MSRP)로 data/가격표.txt 를 만든다."""
# 사용: python tools/build_prices.py <작업폴더>  (작업폴더에 book.txt, prices2.json, msrp_lines.txt 필요. 매달 Claude가 갱신)
import json, re, sys, collections
SP = sys.argv[1]
sys.path.insert(0, SP)
from specparse import parse

items = json.load(open(f'{SP}/prices2.json'))
msrp = open(f'{SP}/msrp_lines.txt').read().splitlines()
book = open(f'{SP}/book.txt').read()

def norm_series(s):
    return s.replace('THE NEW BMW ', 'THE ').replace(' LCI', '').strip().rstrip('.')

# 1) Approach Book 트림 이름 + 사양, 차종 묶음별
groups = collections.OrderedDict()
for it in items:
    s = norm_series(it['series'] or ('THE 2 Coupe' if 'M240i' in it['model'] else '기타'))
    m = it['model']
    if it['alt']:
        if '(xDrive)' in m: b = m.replace('(xDrive)', '').strip(); names = [b, b + ' xDrive']
        elif '30d/40i' in m: names = [m.replace('30d/40i', '30d'), m.replace('30d/40i', '40i')]
        elif '(6인승)' in m: b = re.sub(r'\s*7인승|\s*\(6인승\)', '', m).strip(); names = [b + ' 7인승', b + ' 6인승']
        elif '(7인승)' in m: b = m.replace('(7인승)', '').strip(); names = [b + ' 5인승', b + ' 7인승']
        else: names = [m]
    else:
        names = [m.replace('7인 승', '7인승')]
    names = [n.replace('주요사양 ', '').replace('(만원) ', '').replace('eDriv40', 'eDrive40') for n in names]
    specs = ' / '.join(x for x in it['specs'] if not re.match(r'^(THE |※|\||-----)', x))
    specs = re.sub(r'\s*THE [^/]*$', '', specs)[:900]
    groups.setdefault(s, []).append((names, specs))

# 2) 차종 묶음별 검색어
def tokens_for(s, rows):
    toks = set()
    for names, _ in rows:
        for n in names:
            f = n.split()[0]
            toks.add(n.split()[1] if f.upper() == 'BMW' else f)
    num = re.match(r'THE (\d)', s)
    if num and not re.search(r'M\d', s): toks.add(f"{num.group(1)}시리즈")
    for x in re.findall(r'\b(X\d M|M\d|iX\d?|i\d|X\d|Z4)\b', s): toks.add(x)
    return [t for t in sorted(toks) if t and not t.startswith('(') and not re.fullmatch(r'\d|Z9\w|I5|I7', t)]

sections = [dict(name=s, toks=tokens_for(s, rows), rows=rows, prices=[], specs=[]) for s, rows in groups.items()]
sections.append(dict(name='THE XM', toks=['XM'], rows=[], prices=[], specs=[]))

# 3) 정가(MSRP)를 차종 묶음에 배정
def flags(n):
    n = n.lower()
    return dict(touring='touring' in n, conv='convertible' in n, gc='gran coupe' in n,
                coupe='coupe' in n and 'gran' not in n, at='active tourer' in n)
def hit(t, txt): return re.search(rf"(?<![A-Za-z0-9]){re.escape(t)}(?![0-9])", txt, re.I)
for line in msrp:
    nm = line[2:].split(':')[0]
    is_m = 'competition' in nm.lower() or bool(re.match(r'M[2-8]\b', nm)) or nm.startswith('XM')
    cands = [s for s in sections if any(hit(t, nm) for t in s['toks'])]
    want = flags(nm)
    best = [s for s in cands if flags(s['name']) == want and bool(re.search(r'THE (X\d M|M\d|XM)', s['name'])) == is_m]
    best = best or [s for s in cands if bool(re.search(r'THE (X\d M|M\d|XM)', s['name'])) == is_m] or cands
    for s in best: s['prices'].append(line.replace('XM Label_Indi', 'XM Label Individual'))

# 4) Approach Book 제원표 → 모델별로 분명한 값만
pages = re.split(r'\[\*\*Page (\d+)\*\*\]\(\)', book)
spec_pages = collections.defaultdict(list)
for i in range(1, len(pages), 2):
    body = pages[i + 1]
    if '배기량' not in body: continue
    lines = [l.strip() for l in body.splitlines() if l.strip() and l.strip() not in ('|', '| :-: |', '|  |', '-----')]
    series = ''
    for l in reversed(lines):
        m = re.match(r'(THE [^※]+?)\.?\s*(※|$)', l)
        if m: series = norm_series(m.group(1)); break
    toks = [re.sub(r'\*\*|\\', '', l).strip() for l in lines if not l.startswith('※') and not re.match(r'^THE ', l)]
    for model, vals in parse(toks).items():
        if vals: spec_pages[series].append(f"- {model}: " + ", ".join(vals))
for s in sections:
    s['specs'] = spec_pages.get(s['name'], [])

out = ["# BMW 가격표", "",
       "판매가격(정가): 2026_OCTOBER_V1.2 가격표의 MSRP (만원, VAT 포함). 연식·생산 차수(P1/P2)에 따라 가격이 다를 수 있음.",
       "주요 사양·제원: 한독모터스 용산전시장 Approach Book 2026년 10월 v1.2",
       "제원의 모델 이름은 엔진 기준이라 트림 이름 앞부분과 맞춰 보세요. 예: 'X3 20' → X3 xDrive 20 M Sport",
       "※ 차량의 옵션 및 가격은 성능 개선이나 당사 사정에 따라 예고없이 변동될 수 있습니다.",
       "※ 제원표의 연비는 표준모드에 의한 연비로서 실주행 연비와 차이가 있습니다.", ""]
for s in sections:
    out += [f"## {s['name']}", f"검색어: {', '.join(s['toks'])}", "[판매가격]"]
    out += s['prices'] or ["- (정가표에 없음: 가격을 쓰지 마세요)"]
    out += ["[제원] (모델이 분명한 값만 옮김. 여기 없는 항목은 쓰지 말 것)"] + (s['specs'] or ["- (제원표 없음)"])
    out += ["[트림별 주요 사양]"]
    for names, specs in s['rows']:
        out += [f"- {n}" for n in names]
        if specs: out.append(f"  주요 사양: {specs}")
    if not s['rows']: out.append("- (Approach Book에 사양 페이지 없음: 사양은 메모에 있는 것만 쓰세요)")
    out.append("")
txt = "\n".join(out)
assert "Guide" not in txt and "SF" not in txt.split("[트림별")[0]
open(f'{SP}/가격표.txt', 'w', encoding='utf-8').write(txt)
print(len(txt), "chars,", len(sections), "sections,", sum(1 for s in sections if s['specs']), "with 제원,",
      sum(len(s['prices']) for s in sections), "price lines")
