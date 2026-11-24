"""장표 린트: 글자 크기, 색, 넘침, 겹침, 빈 공간을 쪽마다 검사한다.

부르는 법: python3.13 -I 도구/린트.py <index.html> [쪽 번호 ...] [--shot 폴더]
다 나온 상태(?static)에서 검사한다. 하나라도 걸리면 종료 코드 1.
"""
import json, sys, pathlib
from playwright.sync_api import sync_playwright

SIZES = {64, 40, 30, 24, 18}
COLORS = {"#0f1318","#161b22","#e6edf3","#9da7b3","#6e7681","#262c36","#0b0e13","#c9d1d9","#6e7681","#58a6ff","#13233a","#ff7b5c","#3a1d17","#3fb950"}
SAFE = dict(left=64, right=1856, top=40, bottom=1060)
MAX_GAP_Y, MAX_GAP_X = 96, 160

JS = r"""
() => {
  const s = document.querySelector('.slide.cur');
  const out = {texts: [], colors: [], blocks: [], overflow: []};
  const hex = c => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return c;
    const p = m[1].split(',').map(x => parseFloat(x)); if (p.length > 3 && p[3] === 0) return 'transparent';
    return '#' + p.slice(0,3).map(v => Math.round(v).toString(16).padStart(2,'0')).join(''); };
  const vis = el => { const cs = getComputedStyle(el); return cs.display !== 'none' && cs.visibility !== 'hidden' && parseFloat(cs.opacity) > 0; };
  const all = [s, ...s.querySelectorAll('*')];
  for (const el of all) {
    if (!vis(el) || el.closest('defs, clipPath')) continue;
    const cs = getComputedStyle(el);
    const own = [...el.childNodes].filter(n => n.nodeType === 3 && n.textContent.trim());
    const tag = el.tagName.toLowerCase();
    const name = tag + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : '');
    if (own.length) {
      const r = document.createRange(); let box = null; const rects = [];
      for (const n of own) { r.selectNodeContents(n); for (const q of r.getClientRects()) {
        if (q.width < 1) continue; rects.push({l: q.left, t: q.top, r: q.right, b: q.bottom});
        box = box ? {l: Math.min(box.l, q.left), t: Math.min(box.t, q.top), r: Math.max(box.r, q.right), b: Math.max(box.b, q.bottom)} : {l: q.left, t: q.top, r: q.right, b: q.bottom}; } }
      if (box) out.texts.push({name, rects, anc: [...(function*(){ let p = el.parentElement; while (p && p !== s) { yield all.indexOf(p); p = p.parentElement; } })()], text: own.map(n => n.textContent.trim()).join(' ').slice(0, 40), size: parseFloat(cs.fontSize), box,
        allow: !!el.closest('[data-lint-overlap]'), path: [...(function*(){ let p = el; while (p && p !== s) { yield p; p = p.parentElement; } })()].length, id: all.indexOf(el)});
      out.colors.push({name, prop: 'color', v: hex(cs.color)});
      if (cs.display !== 'inline' && !(el instanceof SVGElement) && el.clientWidth > 0 &&
          (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 2))
        out.overflow.push({name, sw: el.scrollWidth, cw: el.clientWidth, sh: el.scrollHeight, ch: el.clientHeight});
    }
    const bg = hex(cs.backgroundColor); if (bg !== 'transparent') out.colors.push({name, prop: 'background', v: bg});
    if (parseFloat(cs.borderTopWidth) > 0) out.colors.push({name, prop: 'border', v: hex(cs.borderTopColor)});
    if (el instanceof SVGElement && tag !== 'svg' && tag !== 'g') {
      for (const p of ['fill', 'stroke']) { if (p === 'fill' && tag === 'line') continue; const v = cs[p]; if (v && v !== 'none' && !v.startsWith('url')) out.colors.push({name, prop: p, v: hex(v)}); }
    }
    if (el.matches('[data-blk], svg, canvas, .card, .term, img')) { const q = el.getBoundingClientRect(); if (q.width > 1) out.blocks.push({name, l: q.left, t: q.top, r: q.right, b: q.bottom}); }
  }
  // 칸 안의 빈 공간: 칸(.cols의 자식, .card, .term, [data-col])의 내용 끝과 칸 끝 사이
  out.cells = [];
  for (const c of s.querySelectorAll('.cols > *, .card, .term, [data-col]')) {
    if (!vis(c)) continue;
    const cs = getComputedStyle(c), q = c.getBoundingClientRect();
    const inTop = q.top + parseFloat(cs.paddingTop) + parseFloat(cs.borderTopWidth);
    const inBot = q.bottom - parseFloat(cs.paddingBottom) - parseFloat(cs.borderBottomWidth);
    let lo = Infinity, hi = -Infinity;
    const r = document.createRange();
    for (const el of c.querySelectorAll('*')) {
      if (!vis(el)) continue;
      const rs = [];
      if (el.matches('svg, canvas, img, .card, .term, [data-blk]')) rs.push(el.getBoundingClientRect());
      for (const n of el.childNodes) if (n.nodeType === 3 && n.textContent.trim()) { r.selectNodeContents(n); rs.push(...r.getClientRects()); }
      for (const x of rs) if (x.height > 0) { lo = Math.min(lo, x.top); hi = Math.max(hi, x.bottom); }
    }
    // 칸 안 자식 사이 빈 공간
    const kids = [...c.children].filter(vis).map(k => k.getBoundingClientRect()).filter(k => k.height > 0).sort((a, b) => a.top - b.top);
    let inner = 0; for (let i = 1; i < kids.length; i++) inner = Math.max(inner, kids[i].top - kids[i-1].bottom);
    if (hi > -Infinity) out.cells.push({name: c.tagName.toLowerCase() + '.' + (c.className || ''), top: lo - inTop, bottom: inBot - hi, inner});
  }
  const h = s.querySelector('.head').getBoundingClientRect(), f = s.querySelector('.src').getBoundingClientRect();
  out.region = {top: h.bottom, bottom: f.top};
  return out;
}
"""

def gaps(intervals, lo, hi):
    iv = sorted((max(lo, a), min(hi, b)) for a, b in intervals if b > lo and a < hi)
    res, cur = [], lo
    for a, b in iv:
        if a > cur: res.append((cur, a))
        cur = max(cur, b)
    if hi > cur: res.append((cur, hi))
    return res

def check(page, n):
    d = page.evaluate(JS)
    errs = []
    for t in d["texts"]:
        if round(t["size"]) not in SIZES: errs.append(f"글자 크기 {t['size']}px: {t['name']} '{t['text']}'")
        b = t["box"]
        if b["l"] < SAFE["left"] or b["r"] > SAFE["right"] or b["t"] < SAFE["top"] or b["b"] > SAFE["bottom"]:
            errs.append(f"안전 영역 밖: {t['name']} '{t['text']}' {b}")
    for c in d["colors"]:
        if c["v"] not in COLORS and c["v"] != "transparent": errs.append(f"토큰 밖 색 {c['v']} ({c['prop']}): {c['name']}")
    for o in d["overflow"]: errs.append(f"넘침: {o['name']} 가로 {o['sw']}/{o['cw']} 세로 {o['sh']}/{o['ch']}")
    T = d["texts"]
    for i in range(len(T)):
        for j in range(i + 1, len(T)):
            if T[i]["id"] in T[j]["anc"] or T[j]["id"] in T[i]["anc"]: continue
            if T[i]["allow"] and T[j]["allow"]: continue
            hit = None
            for a in T[i]["rects"]:
                for b in T[j]["rects"]:
                    w = min(a["r"], b["r"]) - max(a["l"], b["l"]); h = min(a["b"], b["b"]) - max(a["t"], b["t"])
                    if w > 2 and h > 2: hit = (w, h)
            if hit: errs.append(f"겹침: '{T[i]['text']}' ↔ '{T[j]['text']}' ({hit[0]:.0f}×{hit[1]:.0f})")
    rg = d["region"]
    boxes = [t["box"] for t in T if t["box"]["t"] >= rg["top"] - 1 and t["box"]["b"] <= rg["bottom"] + 1] + \
            [dict(l=b["l"], t=b["t"], r=b["r"], b=b["b"]) for b in d["blocks"]]
    gy = [g for g in gaps([(b["t"], b["b"]) for b in boxes], rg["top"], rg["bottom"]) if g[1] - g[0] > MAX_GAP_Y]
    gx = [g for g in gaps([(b["l"], b["r"]) for b in boxes], 96, 1824) if g[1] - g[0] > MAX_GAP_X]
    for c in d["cells"]:
        if c["bottom"] > MAX_GAP_Y: errs.append(f"칸 아래 빈 공간 {c['bottom']:.0f}px: {c['name']}")
        if c["inner"] > MAX_GAP_Y: errs.append(f"칸 안 빈 공간 {c['inner']:.0f}px: {c['name']}")
        if c["top"] > MAX_GAP_Y: errs.append(f"칸 위 빈 공간 {c['top']:.0f}px: {c['name']}")
    for g in gy: errs.append(f"세로 빈 공간 {g[1]-g[0]:.0f}px (y {g[0]:.0f}~{g[1]:.0f})")
    for g in gx: errs.append(f"가로 빈 공간 {g[1]-g[0]:.0f}px (x {g[0]:.0f}~{g[1]:.0f})")
    return errs

def main():
    args = sys.argv[1:]; shot = None
    if "--shot" in args: i = args.index("--shot"); shot = pathlib.Path(args[i + 1]); del args[i:i + 2]
    html = pathlib.Path(args[0]).resolve(); pages = [int(x) for x in args[1:]]
    bad = 0
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome")
        pg = br.new_page(viewport={"width": 1920, "height": 1080})
        pg.goto(html.as_uri() + "?static&p=1"); pg.wait_for_timeout(300)
        total = pg.evaluate("document.querySelectorAll('.slide').length")
        for n in (pages or range(1, total + 1)):
            pg.goto(html.as_uri() + f"?static&p={n}"); pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(400)
            errs = check(pg, n)
            print(f"{n}쪽: {'통과' if not errs else f'{len(errs)}건'}")
            for e in errs: print("   ", e)
            bad += bool(errs)
            if shot: shot.mkdir(parents=True, exist_ok=True); pg.screenshot(path=str(shot / f"p{n}.png"))
        br.close()
    sys.exit(1 if bad else 0)

main()
