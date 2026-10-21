import re
KEEP = {"전장":"전장(mm)","전폭":"전폭(mm)","전고":"전고(mm)","휠베이스":"휠베이스(mm)","종류":"엔진","배기량 (cc)":"배기량(cc)",
        "최고 출력 (마력/rpm)":"최고출력(마력/rpm)","최대 토크 (kg.m/rpm)":"최대토크(kg.m/rpm)","변속기":"변속기","변속 시스템":"변속기",
        "구동 방식":"구동","안전 최고 속도 (km/h)":"최고속도(km/h)","안전 최고 속도":"최고속도(km/h)","0-100km/h":"0-100km/h(초)",
        "복합 연비(km/L)":"복합연비(km/L)","1회 충전 주행 거리 (km)":"1회 충전 주행거리(km)","연료 탱크 용량 (L)":"연료탱크(L)"}
DROP = {"트렁크 용량 (L)","외관","(mm)","엔진","성능","연비","PHEV","공차 중량 (kg)","차량 총 중량 (kg)","CO2 배출량 (g/km)","타이어 규격","(시내/고속)","전기차","배터리"}
def parse(tokens):
    i = next((k for k,t in enumerate(tokens) if t in KEEP or t in DROP), None)
    if i is None: return {}
    models = [t for t in tokens[:i] if t]
    n = len(models)
    out = {m:[] for m in models}
    k = i
    while k < len(tokens):
        lab = tokens[k]; k += 1
        vals = []
        while k < len(tokens) and tokens[k] not in KEEP and tokens[k] not in DROP:
            vals.append(tokens[k]); k += 1
        if lab not in KEEP or not vals or n == 0: continue
        name = KEEP[lab]
        if name.startswith(("최고출력","최대토크")) and len(vals) == 2*n and all("/" not in v for v in vals):
            vals = [f"{vals[2*j]}/{vals[2*j+1]}" for j in range(n)]
        if len(vals) == 1:
            for m in models: out[m].append(f"{name} {vals[0]}")
        elif len(vals) == n:
            for m, v in zip(models, vals): out[m].append(f"{name} {v}")
        # 값 개수가 모델 수와 안 맞으면(병합된 칸) 잘못 짝지을 수 있어 버린다
    return out
