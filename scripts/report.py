"""Relatório da equipa Creative Mode, desenhado com a identidade da marca.

Lê a atividade da organização no GitHub (commits, pull requests e revisões
dos últimos N dias), desenha três cartões em SVG (resumo, equipa e
repositórios) em versão escura e clara, e reescreve o bloco entre
<!-- relatorio:inicio --> e <!-- relatorio:fim --> em profile/README.md.

O texto dos cartões é convertido em contornos com as fontes da marca
(Unbounded e Archivo, em scripts/fonts), para ficar igual em qualquer ecrã.

Variáveis de ambiente:
  ORG     organização (por omissão: creative-mode)
  DAYS    janela em dias (por omissão: 30)
  TOKEN   token com leitura dos repositórios da organização
  REPOS   opcional, lista separada por vírgulas para limitar os repositórios
  README  caminho do README (por omissão: profile/README.md)
  DEMO    opcional, "1" desenha com dados de exemplo (só para pré-visualizar)
"""
import json, os, re, statistics, sys, urllib.request, urllib.error
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

ORG = os.environ.get("ORG", "creative-mode")
DAYS = int(os.environ.get("DAYS", "30"))
TOKEN = os.environ.get("TOKEN", "")
README = os.environ.get("README", "profile/README.md")
OUT = os.path.dirname(README) or "."
NOW = datetime.now(timezone.utc)
SINCE = NOW - timedelta(days=DAYS)
START, END = "<!-- relatorio:inicio -->", "<!-- relatorio:fim -->"
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- dados

def api(path):
    url = path if path.startswith("http") else f"https://api.github.com/{path.lstrip('/')}"
    out = []
    while url:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        if TOKEN:
            req.add_header("Authorization", f"Bearer {TOKEN}")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
                link = r.headers.get("Link", "")
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 409):
                return out
            raise
        if not isinstance(data, list):
            return data
        out += data
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m else None
    return out


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def human(login):
    return bool(login) and not login.endswith("[bot]") and login not in ("github-actions", "dependabot")


def collect():
    if os.environ.get("REPOS"):
        repos = [r.strip() for r in os.environ["REPOS"].split(",") if r.strip()]
    else:
        repos = [r["name"] for r in api(f"orgs/{ORG}/repos?type=all&per_page=100")
                 if not r.get("archived") and not r.get("fork") and r["name"] != ".github"]
    people = defaultdict(lambda: defaultdict(int))
    per_repo, weeks = {}, [0] * ((DAYS + 6) // 7)
    first_review, merged_total, merged_reviewed, waiting = [], 0, 0, []
    for repo in sorted(repos):
        rc, rm, last = 0, 0, None
        for c in api(f"repos/{ORG}/{repo}/commits?since={SINCE.isoformat()}&per_page=100"):
            who, when = (c.get("author") or {}).get("login"), ts(c["commit"]["author"]["date"])
            if not human(who):
                continue
            people[who]["commits"] += 1
            rc += 1
            last = max(last, when) if last else when
            weeks[min(len(weeks) - 1, (NOW - when).days // 7)] += 1
        for pr in api(f"repos/{ORG}/{repo}/pulls?state=all&sort=updated&direction=desc&per_page=100"):
            if ts(pr["updated_at"]) < SINCE:
                break
            author = pr["user"]["login"]
            created, merged = ts(pr["created_at"]), ts(pr.get("merged_at"))
            reviews = [r for r in api(f"repos/{ORG}/{repo}/pulls/{pr['number']}/reviews?per_page=100")
                       if human((r.get("user") or {}).get("login")) and r["user"]["login"] != author and r.get("submitted_at")]
            for r in reviews:
                if ts(r["submitted_at"]) >= SINCE:
                    people[r["user"]["login"]]["reviews"] += 1
            if human(author):
                if created >= SINCE:
                    people[author]["opened"] += 1
                    if reviews:
                        first_review.append((min(ts(r["submitted_at"]) for r in reviews) - created).total_seconds() / 3600)
                if merged and merged >= SINCE:
                    people[author]["merged"] += 1
                    rm += 1
                    merged_total += 1
                    merged_reviewed += bool(reviews)
                if pr["state"] == "open" and not pr.get("draft") and not reviews and (NOW - created).days >= 3:
                    waiting.append((repo, pr["number"], pr["title"], (NOW - created).days, pr["html_url"]))
            last = max(last, ts(pr["updated_at"])) if last else ts(pr["updated_at"])
        if rc or rm:
            per_repo[repo] = (rc, rm, last)
    return dict(people=people, repos=per_repo, weeks=list(reversed(weeks)),
                median=statistics.median(first_review) if first_review else None,
                merged=merged_total, reviewed=merged_reviewed, waiting=waiting)


def demo():
    people = defaultdict(lambda: defaultdict(int))
    for who, c, o, m, r in [("jedin01", 48, 9, 8, 6), ("ana-dev", 31, 6, 5, 11), ("mbala", 22, 4, 4, 7), ("kiesse", 12, 3, 2, 3)]:
        people[who].update(commits=c, opened=o, merged=m, reviews=r)
    repos = {"kixi": (44, 9, NOW - timedelta(hours=3)), "kixi-frontend": (39, 7, NOW - timedelta(days=1)),
             "index": (20, 2, NOW - timedelta(days=2)), "tourie": (10, 1, NOW - timedelta(days=9))}
    return dict(people=people, repos=repos, weeks=[14, 22, 31, 18, 28], median=5.4, merged=19, reviewed=16,
                waiting=[("kixi", 42, "Exemplo de PR à espera", 4, "https://github.com/creative-mode")])

# ---------------------------------------------------------------- desenho

THEMES = {
    "dark":  dict(bg="#0A0A0A", panel="#141414", line="#262626", ink="#F4F4F4", soft="#C9C9C9", muted="#9A9A9A", dim="#3A3A3A", accent="#DF7BEF", on_accent="#0A0A0A"),
    "light": dict(bg="#F4F4F4", panel="#EAEAEA", line="#DCDCDC", ink="#0A0A0A", soft="#3A3A3A", muted="#6A6A6A", dim="#C4C4C4", accent="#9525A9", on_accent="#F4F4F4"),
}


class Face:
    def __init__(self, file, track=0.0):
        self.f = TTFont(os.path.join(HERE, "fonts", file))
        self.gs, self.cmap, self.upm = self.f.getGlyphSet(), self.f.getBestCmap(), self.f["head"].unitsPerEm
        self.track = track

    def width(self, s, size):
        w = sum(self.f["hmtx"][self.cmap.get(ord(ch), self.cmap[ord("?")])][0] for ch in s) * size / self.upm
        return w + self.track * size * max(len(s) - 1, 0)

    def path(self, s, size, x, y, fill, anchor="start"):
        if anchor == "end":
            x -= self.width(s, size)
        elif anchor == "middle":
            x -= self.width(s, size) / 2
        k, ds = size / self.upm, []
        for ch in s:
            g = self.cmap.get(ord(ch), self.cmap[ord("?")])
            pen = SVGPathPen(self.gs)
            self.gs[g].draw(TransformPen(pen, (k, 0, 0, -k, x, y)))
            ds.append(pen.getCommands())
            x += self.f["hmtx"][g][0] * k + self.track * size
        return f'<path d="{" ".join(d for d in ds if d)}" fill="{fill}"/>'


DISPLAY = Face("Unbounded-700.ttf", -0.035)
TEXT = Face("Archivo-500.ttf")
STRONG = Face("Archivo-600.ttf")


def ring(x, y, w, h, frac, t, stroke=None):
    """O símbolo da marca como medidor: anel alongado, preenchido na proporção `frac`."""
    sw = stroke or max(2.0, h * 0.22)
    pad = sw * 0.95
    inner_w, inner_h = w - 2 * pad, h - 2 * pad
    fw = max(inner_h, inner_w * min(max(frac, 0), 1)) if frac > 0 else 0
    out = (f'<rect x="{x + sw/2:.1f}" y="{y + sw/2:.1f}" width="{w - sw:.1f}" height="{h - sw:.1f}" rx="{(h - sw)/2:.1f}" '
           f'fill="none" stroke="{t["ink"]}" stroke-width="{sw:.1f}"/>')
    if fw:
        out += f'<rect x="{x + pad:.1f}" y="{y + pad:.1f}" width="{fw:.1f}" height="{inner_h:.1f}" rx="{inner_h/2:.1f}" fill="{t["accent"]}"/>'
    return out


def card(w, h, t, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="24" fill="{t["bg"]}" stroke="{t["line"]}"/>{body}</svg>')


def data_pt(d):
    return f"{d.day} {MESES[d.month - 1]} {d.year}"


def horas(h):
    if h is None:
        return "—"
    return f"{h:.0f} h" if h < 48 else f"{h / 24:.1f} d".replace(".", ",")


def resumo(d, t):
    W, H = 1280, 470
    commits = sum(p["commits"] for p in d["people"].values())
    pct = d["reviewed"] / d["merged"] if d["merged"] else None
    b = [STRONG.path("RELATÓRIO DA EQUIPA", 14, 56, 72, t["muted"]),
         TEXT.path(f"Últimos {DAYS} dias · {data_pt(NOW)}", 16, W - 56, 72, t["muted"], "end"),
         DISPLAY.path("Como estamos a trabalhar", 44, 56, 136, t["ink"])]
    kpis = [(str(commits), "commits"), (str(d["merged"]), "PRs integrados"),
            (f"{round(pct * 100)}%" if pct is not None else "—", "revistos antes de integrar"),
            (horas(d["median"]), "até à primeira revisão")]
    colw = (W - 112) / 4
    for i, (v, lab) in enumerate(kpis):
        x = 56 + i * colw
        b.append(f'<rect x="{x:.1f}" y="176" width="{colw - 24:.1f}" height="1" fill="{t["line"]}"/>')
        b.append(DISPLAY.path(v, 56, x, 252, t["accent"] if i == 2 else t["ink"]))
        b.append(TEXT.path(lab, 16, x, 282, t["muted"]))
        if i == 2 and pct is not None:
            b.append(ring(x, 298, min(160, colw - 24), 22, pct, t))
    # ritmo semanal: um anel por semana, preenchido na proporção da semana mais ativa
    b.append(STRONG.path("Ritmo semanal de commits", 16, 56, 350, t["soft"]))
    weeks, top = d["weeks"], max(d["weeks"]) or 1
    gap, rw = 16, (W - 112 - 16 * (len(weeks) - 1)) / len(weeks)
    for i, n in enumerate(weeks):
        x = 56 + i * (rw + gap)
        b.append(ring(x, 372, rw, 36, n / top, t))
        lab = "esta semana" if i == len(weeks) - 1 else f"há {len(weeks) - 1 - i} sem."
        b.append(TEXT.path(lab, 14, x + 4, 436, t["muted"]))
        b.append(STRONG.path(str(n), 14, x + rw - 4, 436, t["soft"], "end"))
    return card(W, H, t, "".join(b))


def table(title, rows, cols, t, label_fn):
    """rows: [(label, bar_value, [valores...])]; a primeira coluna numérica leva o anel."""
    W, head, rh = 1280, 150, 64
    H = head + rh * max(len(rows), 1) + 40
    b = [DISPLAY.path(title, 30, 56, 78, t["ink"])]
    xs = [600, 860, 1010, 1160]           # âncoras à direita das colunas numéricas
    for x, c in zip(xs, cols):
        b.append(STRONG.path(c, 14, x, 124, t["muted"], "end"))
    b.append(f'<rect x="56" y="140" width="{W - 112}" height="1" fill="{t["line"]}"/>')
    top = max([r[1] for r in rows] or [1]) or 1
    for i, (label, bar, vals) in enumerate(rows):
        y = head + i * rh
        b.append(label_fn(label, y, t))
        b.append(ring(330, y + 18, 200, 28, bar / top, t))
        for j, (x, v) in enumerate(zip(xs, vals)):
            b.append((DISPLAY if j == 0 else STRONG).path(str(v), 22 if j == 0 else 18, x, y + 40, t["ink"] if j == 0 else t["soft"], "end"))
        b.append(f'<rect x="56" y="{y + rh - 1}" width="{W - 112}" height="1" fill="{t["line"]}"/>')
    if not rows:
        b.append(TEXT.path("Sem atividade neste período.", 18, 56, head + 40, t["muted"]))
    return card(W, H, t, "".join(b))


def person(label, y, t):
    ini = (label[:2]).upper()
    return (f'<circle cx="76" cy="{y + 32}" r="20" fill="{t["accent"]}"/>'
            + STRONG.path(ini, 14, 76, y + 37, t["on_accent"], "middle")
            + STRONG.path(label, 20, 112, y + 39, t["ink"]))


def repo_label(label, y, t):
    return STRONG.path(label, 20, 56, y + 39, t["ink"])


def picture(name, alt):
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="./{name}-dark.svg">'
            f'<img alt="{alt}" src="./{name}-light.svg" width="100%"></picture>')


def main():
    d = demo() if os.environ.get("DEMO") == "1" else collect()
    people = sorted(d["people"].items(), key=lambda kv: kv[0].lower())
    team_rows = [(who, p["commits"], [p["commits"], p["opened"], p["merged"], p["reviews"]]) for who, p in people]
    repo_rows = [(r, c, [c, m, "", data_pt(l) if l else ""]) for r, (c, m, l) in
                 sorted(d["repos"].items(), key=lambda kv: kv[1][2] or SINCE, reverse=True)]
    for name, t in THEMES.items():
        open(f"{OUT}/relatorio-resumo-{name}.svg", "w").write(resumo(d, t))
        open(f"{OUT}/relatorio-equipa-{name}.svg", "w").write(
            table("Equipa", team_rows, ["Commits", "PRs abertos", "Integrados", "Revisões"], t, person))
        open(f"{OUT}/relatorio-repositorios-{name}.svg", "w").write(
            table("Repositórios", repo_rows, ["Commits", "PRs integrados", "", "Última atividade"], t, repo_label))

    L = [START, "", picture("relatorio-resumo", "Resumo da atividade da equipa"), "",
         picture("relatorio-equipa", "Atividade por pessoa"), "",
         picture("relatorio-repositorios", "Atividade por repositório"), ""]
    if d["waiting"]:
        L += ["**À espera de revisão**", ""]
        for repo, n, title, days, url in sorted(d["waiting"], key=lambda w: -w[3])[:5]:
            L.append(f"- [{repo}#{n}]({url}) {title} · há {days} dias")
        L.append("")
    L += [f"<sub>Atualizado automaticamente todas as segundas-feiras · {data_pt(NOW)}</sub>", "", END]
    block = "\n".join(L)
    text = open(README, encoding="utf-8").read()
    if START in text and END in text:
        text = text[:text.index(START)] + block + text[text.index(END) + len(END):]
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    open(README, "w", encoding="utf-8").write(text)
    print(f"{len(d['repos'])} repositórios com atividade, {len(people)} pessoas")


if __name__ == "__main__":
    sys.exit(main())
