"""Atualiza o relatório de atividade da organização em profile/README.md.

Lê a API do GitHub (commits, pull requests e revisões dos últimos N dias)
e reescreve o bloco entre <!-- relatorio:inicio --> e <!-- relatorio:fim -->.
Só usa a biblioteca padrão do Python.

Variáveis de ambiente:
  ORG       organização (por omissão: creative-mode)
  DAYS      janela em dias (por omissão: 30)
  TOKEN     token com leitura dos repositórios da organização
  REPOS     opcional, lista separada por vírgulas para limitar os repositórios
  README    caminho do README (por omissão: profile/README.md)
"""
import json, os, re, statistics, sys, urllib.request, urllib.error
from collections import defaultdict
from datetime import datetime, timedelta, timezone

ORG = os.environ.get("ORG", "creative-mode")
DAYS = int(os.environ.get("DAYS", "30"))
TOKEN = os.environ.get("TOKEN", "")
README = os.environ.get("README", "profile/README.md")
NOW = datetime.now(timezone.utc)
SINCE = NOW - timedelta(days=DAYS)
START, END = "<!-- relatorio:inicio -->", "<!-- relatorio:fim -->"
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def api(path):
    """GET com paginação; devolve a lista completa (ou o objeto, se não for lista)."""
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
            if e.code in (403, 404, 409):   # sem acesso ou repositório vazio
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
    return login and not login.endswith("[bot]") and login not in ("github-actions", "dependabot")


def data_pt(d):
    return f"{d.day} {MESES[d.month - 1]} {d.year}"


def horas(h):
    if h is None:
        return "sem dados"
    return f"{h:.0f} h" if h < 48 else f"{h / 24:.1f} dias".replace(".", ",")


def spark(values):
    blocks = "▁▂▃▄▅▆▇█"
    top = max(values) or 1
    return "".join(blocks[min(7, round(v / top * 7))] if v else "▁" for v in values)


def main():
    if os.environ.get("REPOS"):
        repos = [r.strip() for r in os.environ["REPOS"].split(",") if r.strip()]
    else:
        repos = [r["name"] for r in api(f"orgs/{ORG}/repos?type=all&per_page=100")
                 if not r.get("archived") and not r.get("fork") and r["name"] != ".github"]

    people = defaultdict(lambda: defaultdict(int))
    per_repo = {}
    weeks = [0] * ((DAYS + 6) // 7)
    first_review, merged_total, merged_reviewed = [], 0, 0
    waiting = []

    for repo in sorted(repos):
        commits = api(f"repos/{ORG}/{repo}/commits?since={SINCE.isoformat()}&per_page=100")
        rc, last = 0, None
        for c in commits:
            who = (c.get("author") or {}).get("login")
            when = ts(c["commit"]["author"]["date"])
            if not human(who):
                continue
            people[who]["commits"] += 1
            rc += 1
            last = max(last, when) if last else when
            weeks[min(len(weeks) - 1, (NOW - when).days // 7)] += 1

        rm = 0
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
            if not human(author):
                continue
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

        if rc or rm or last:
            per_repo[repo] = (rc, rm, last)

    commits_total = sum(p["commits"] for p in people.values())
    median = statistics.median(first_review) if first_review else None
    pct = f"{round(merged_reviewed / merged_total * 100)}%" if merged_total else "sem dados"

    L = [START, "", "### Como estamos a trabalhar", "",
         f"<sub>Últimos {DAYS} dias · atualizado a {data_pt(NOW)}</sub>", "",
         "| Commits | PRs integrados | PRs revistos antes de integrar | Até à primeira revisão |",
         "|:-:|:-:|:-:|:-:|",
         f"| **{commits_total}** | **{merged_total}** | **{pct}** | **{horas(median)}**{" (mediana)" if median is not None else ""} |", "",
         f"Ritmo semanal de commits, da semana mais antiga para a atual: `{spark(list(reversed(weeks)))}`", ""]

    if people:
        L += ["#### Equipa", "", "| | Commits | PRs abertos | PRs integrados | Revisões feitas |", "|---|:-:|:-:|:-:|:-:|"]
        for who in sorted(people, key=str.lower):
            p = people[who]
            L.append(f'| <img src="https://github.com/{who}.png?size=40" width="20" height="20" align="center"> [{who}](https://github.com/{who}) '
                     f'| {p["commits"]} | {p["opened"]} | {p["merged"]} | {p["reviews"]} |')
        L.append("")

    if per_repo:
        L += ["#### Repositórios", "", "| | Commits | PRs integrados | Última atividade |", "|---|:-:|:-:|:-:|"]
        for repo, (rc, rm, last) in sorted(per_repo.items(), key=lambda kv: kv[1][2] or SINCE, reverse=True):
            L.append(f"| [{repo}](https://github.com/{ORG}/{repo}) | {rc} | {rm} | {data_pt(last) if last else ''} |")
        L.append("")

    L += ["#### À espera de revisão", ""]
    if waiting:
        for repo, n, title, days, url in sorted(waiting, key=lambda w: -w[3])[:5]:
            L.append(f"- [{repo}#{n}]({url}) {title} · há {days} dias")
    else:
        L.append("Nenhum PR aberto há mais de 3 dias sem revisão.")
    L += ["", "<sub>Gerado automaticamente todas as segundas-feiras a partir da atividade no GitHub.</sub>", "", END]
    block = "\n".join(L)

    text = open(README, encoding="utf-8").read()
    if START in text and END in text:
        text = text[:text.index(START)] + block + text[text.index(END) + len(END):]
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    open(README, "w", encoding="utf-8").write(text)
    print(f"{len(repos)} repositórios, {len(people)} pessoas, {commits_total} commits")


if __name__ == "__main__":
    sys.exit(main())
