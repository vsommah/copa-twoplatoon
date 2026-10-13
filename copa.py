#!/usr/bin/env python3
"""
Copa TwoPlatoon — seeds, sorteio, chaveamento e placares direto da Sleeper.

Uso:
    python copa.py update                  # busca tudo na Sleeper e gera docs/data/cup.json
    python copa.py update --mock           # mesma coisa, com ligas FALSAS (para testar)
    python copa.py update --mock --mock-week 9
    python copa.py freeze                  # trava os seeds (semanas 1-5) manualmente

Só usa a biblioteca padrão do Python (nada para instalar).

Como funciona, em resumo:
  1. Semanas 1-5 -> classificação de cada série (vitórias, depois PF). Depois da
     semana 5 ela é CONGELADA em state/seeds.json e nunca mais muda.
  2. Fase 1 (S6-S7): 56 times = A5..A12 + B + C + D + E. Montamos uma lista
     "global" (A5..A12, B1..B12, C1..., D1..., E1...) e o 1º enfrenta o último,
     o 2º o penúltimo, etc. (é o mesmo critério do ano passado).
  3. Fase 2 (S8-S9): 28 vencedores + A1..A4. Aqui há SORTEIO. Ele usa uma
     semente pública (a soma dos PF da Fase 1), então qualquer um pode conferir.
     O resultado fica salvo em state/draw.json e não muda mais.
  4. Oitavas, Quartas, Semis: o vencedor do jogo 1 enfrenta o do jogo 2, o do
     3 enfrenta o do 4, e assim por diante. S16 = Toilet Bowl, S17 = Final.
"""
import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
API = "https://api.sleeper.app/v1"
SERIES = ["A", "B", "C", "D", "E"]

# (chave, nome, semanas). Todas de ida e volta, menos a final (jogo único).
ROUNDS = [
    ("f1", "Fase 1", [6, 7]),
    ("f2", "Fase 2", [8, 9]),
    ("r16", "Oitavas", [10, 11]),
    ("qf", "Quartas", [12, 13]),
    ("sf", "Semifinais", [14, 15]),
    ("final", "Final", [17]),
]
TOILET_WEEK = 16


# --------------------------------------------------------------------------
# 1) Acesso à Sleeper (e uma versão FALSA para testes)
# --------------------------------------------------------------------------
class Sleeper:
    def _get(self, path):
        req = urllib.request.Request(API + path, headers={"User-Agent": "copa-twoplatoon"})
        for tentativa in range(4):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.load(r)
            except (urllib.error.URLError, TimeoutError) as e:
                if tentativa == 3:
                    raise RuntimeError(f"Falha ao acessar a Sleeper ({path}): {e}")
                time.sleep(2 * (tentativa + 1))

    def nfl_week(self):
        return int(self._get("/state/nfl")["week"])

    def teams(self, league_id):
        """Devolve {roster_id: {"name":..., "owner":...}}"""
        users = {u["user_id"]: u for u in self._get(f"/league/{league_id}/users")}
        out = {}
        for r in self._get(f"/league/{league_id}/rosters"):
            u = users.get(r.get("owner_id"), {})
            owner = u.get("display_name") or "sem dono"
            name = (u.get("metadata") or {}).get("team_name") or owner
            out[r["roster_id"]] = {"name": name.strip(), "owner": owner}
        return out

    def matchups(self, league_id, week):
        return self._get(f"/league/{league_id}/matchups/{week}") or []


class MockSleeper:
    """Ligas falsas (5 séries x 12 times) só para testar o código."""

    def __init__(self, week):
        self.week = week

    def nfl_week(self):
        return self.week

    def teams(self, league_id):
        return {i: {"name": f"Time {league_id}{i}", "owner": f"dono_{league_id}{i}"} for i in range(1, 13)}

    def matchups(self, league_id, week):
        if week >= self.week + 1:  # semana futura: Sleeper devolve zeros
            return [{"roster_id": i, "matchup_id": (i + 1) // 2, "points": 0} for i in range(1, 13)]
        rng = random.Random(f"{league_id}-{week}")
        ids = list(range(1, 13))
        rng.shuffle(ids)
        out = []
        for k, rid in enumerate(ids):
            pts = round(random.Random(f"{league_id}-{week}-{rid}").gauss(225, 35), 2)
            out.append({"roster_id": rid, "matchup_id": k // 2 + 1, "points": pts})
        return out


# --------------------------------------------------------------------------
# 2) Classificação das semanas 1-5 (seeds)
# --------------------------------------------------------------------------
def compute_standings(sl, league_id, weeks):
    """Monta a tabela da série só com as semanas pedidas.
    Ordem: % de vitórias; desempate por PF (regra da Sleeper que vocês já usam)."""
    stats = {rid: dict(roster_id=rid, w=0, l=0, t=0, pf=0.0, pa=0.0, **info)
             for rid, info in sl.teams(league_id).items()}
    for week in weeks:
        jogos = {}
        for m in sl.matchups(league_id, week):
            if m.get("matchup_id") is not None:
                jogos.setdefault(m["matchup_id"], []).append(m)
        for par in jogos.values():
            if len(par) != 2:
                continue
            for x, y in ((par[0], par[1]), (par[1], par[0])):
                px, py = x.get("points") or 0, y.get("points") or 0
                s = stats[x["roster_id"]]
                s["pf"] += px
                s["pa"] += py
                if px > py:
                    s["w"] += 1
                elif px < py:
                    s["l"] += 1
                else:
                    s["t"] += 1
    def chave(s):
        jogos = s["w"] + s["l"] + s["t"]
        pct = (s["w"] + 0.5 * s["t"]) / jogos if jogos else 0
        return (-pct, -s["pf"], s["roster_id"])
    tabela = sorted(stats.values(), key=chave)
    for pos, s in enumerate(tabela, 1):
        s["seed"] = pos
        s["pf"] = round(s["pf"], 2)
        s["pa"] = round(s["pa"], 2)
    return tabela


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def get_seeds(sl, cfg, state_dir, nfl_week, force_freeze=False):
    """Devolve (seeds, congelado?). Congela automaticamente quando a semana 5 termina."""
    path = state_dir / "seeds.json"
    saved = load_json(path)
    if saved:
        return saved["series"], True
    weeks = list(range(1, cfg["seed_week"] + 1))
    series = {s: compute_standings(sl, cfg["leagues"][s], weeks) for s in SERIES}
    for s, tabela in series.items():
        if len(tabela) != cfg.get("teams_per_series", 12):
            raise RuntimeError(f"Série {s} tem {len(tabela)} times; o esperado é {cfg.get('teams_per_series', 12)}.")
    if force_freeze or nfl_week > cfg["seed_week"]:
        save_json(path, {"frozen_at": now_iso(), "series": series})
        return series, True
    return series, False


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# 3) Chaveamento
# --------------------------------------------------------------------------
def make_team(series, row):
    return {
        "id": f"{series}{row['seed']}",
        "series": series,
        "seed": row["seed"],
        "label": f"{row['seed']}-{series}",
        "name": row["name"],
        "owner": row["owner"],
        "roster_id": row["roster_id"],
        "record": f"{row['w']}-{row['l']}" + (f"-{row['t']}" if row["t"] else ""),
        "pf_seed": row["pf"],
    }


class Cup:
    def __init__(self, sl, cfg, seeds, nfl_week, state_dir):
        self.sl, self.cfg, self.nfl_week, self.state_dir = sl, cfg, nfl_week, state_dir
        self.teams = {}
        for s in SERIES:
            for row in seeds[s]:
                t = make_team(s, row)
                self.teams[t["id"]] = t
        self._cache = {}  # (série, semana) -> {roster_id: pontos}
        self.eliminated = {}  # id do time -> nome da fase em que caiu
        self.warnings = []    # avisos (ex.: time sem placar numa semana já encerrada)

    # ---- pontos --------------------------------------------------------
    def week_state(self, week):
        if week < self.nfl_week:
            return "done"
        return "live" if week == self.nfl_week else "future"

    def pts(self, team, week):
        if team is None or self.week_state(week) == "future":
            return None
        key = (team["series"], week)
        if key not in self._cache:
            data = self.sl.matchups(self.cfg["leagues"][team["series"]], week)
            self._cache[key] = {m["roster_id"]: m.get("points") or 0 for m in data}
        pontos = self._cache[key]
        if team["roster_id"] not in pontos and self.week_state(week) == "done":
            self.warnings.append(f"{team['name']} ({team['label']}) não aparece nos confrontos da semana {week} da Sleeper; contei 0.")
        return round(pontos.get(team["roster_id"], 0), 2)

    # ---- um confronto --------------------------------------------------
    def match(self, mid, rnd_name, a, b, weeks, tbd=("", "")):
        legs = []
        for w in weeks:
            legs.append({"week": w, "state": self.week_state(w), "a": self.pts(a, w), "b": self.pts(b, w)})
        def total(side):
            vals = [l[side] for l in legs if l[side] is not None]
            return round(sum(vals), 2) if vals else None
        ta, tb = total("a"), total("b")
        winner, by_tiebreak = None, False
        if a and b and all(l["state"] == "done" for l in legs):
            if ta != tb:
                winner = a if ta > tb else b
            else:  # empate no agregado: melhor PF nas semanas 1-5
                by_tiebreak = True
                winner = a if a["pf_seed"] >= b["pf_seed"] else b
            loser = b if winner is a else a
            self.eliminated[loser["id"]] = rnd_name
        return {
            "id": mid, "a": a, "b": b, "tbd_a": tbd[0], "tbd_b": tbd[1],
            "legs": legs, "total_a": ta, "total_b": tb,
            "winner": winner["id"] if winner else None, "tiebreak": by_tiebreak,
            "_winner": winner,
        }

    # ---- Fase 1 --------------------------------------------------------
    def phase1_pairs(self):
        ordem = [self.teams[f"A{i}"] for i in range(5, 13)]
        for s in SERIES[1:]:
            ordem += [self.teams[f"{s}{i}"] for i in range(1, 13)]
        n = len(ordem)  # 56
        return [(ordem[i], ordem[n - 1 - i]) for i in range(n // 2)]

    # ---- Sorteio da Fase 2 ----------------------------------------------
    def draw_phase2(self, winners, phase1_total):
        """Sorteio reproduzível. Retorna lista de 16 pares [id_a, id_b] em ordem de chave."""
        path = self.state_dir / "draw.json"
        saved = load_json(path)
        if saved:
            return saved
        semente = f"copa-{self.cfg['season']}-{phase1_total:.2f}"
        rng = random.Random(semente)
        top = [self.teams[f"A{i}"] for i in range(1, 5)]
        # A1 e A2 em metades opostas; A3/A4 nos outros dois quartos (sorteados)
        q3, q4 = (4, 12) if rng.random() < 0.5 else (12, 4)
        posicao_a = {0: top[0], 8: top[1], q3: top[2], q4: top[3]}
        pote = list(winners)
        rng.shuffle(pote)
        pares = [None] * 16
        for pos, a in posicao_a.items():
            pares[pos] = [a["id"], pote.pop()["id"]]
        for i in range(16):
            if pares[i] is None:
                pares[i] = [pote.pop()["id"], pote.pop()["id"]]
        assert not pote
        saved = {"seed": semente, "drawn_at": now_iso(), "pairs": pares}
        save_json(path, saved)
        return saved

    # ---- Tudo -------------------------------------------------------------
    def build(self):
        rounds, r_by_key = [], {}

        # Fase 1
        name = ROUNDS[0][1]
        m1 = [self.match(f"F1-{i + 1:02d}", name, a, b, ROUNDS[0][2])
              for i, (a, b) in enumerate(self.phase1_pairs())]
        rounds.append(m1)

        # Fase 2
        name, weeks = ROUNDS[1][1], ROUNDS[1][2]
        draw = None
        if all(m["_winner"] for m in m1):
            total = sum((m["total_a"] or 0) + (m["total_b"] or 0) for m in m1)
            draw = self.draw_phase2([m["_winner"] for m in m1], total)
            m2 = [self.match(f"F2-{i + 1:02d}", name, self.teams[a], self.teams[b], weeks)
                  for i, (a, b) in enumerate(draw["pairs"])]
        else:
            m2 = [self.match(f"F2-{i + 1:02d}", name, None, None, weeks, ("A sortear", "A sortear"))
                  for i in range(16)]
        rounds.append(m2)

        # Oitavas, quartas, semis, final: vencedor do jogo 2k x vencedor do jogo 2k+1
        prev = m2
        for key, name, weeks in ROUNDS[2:]:
            cur = []
            if key == "final":
                pares = [(prev[0], prev[1])]
            else:
                pares = [(prev[2 * i], prev[2 * i + 1]) for i in range(len(prev) // 2)]
            for i, (x, y) in enumerate(pares):
                cur.append(self.match(
                    f"{key.upper()}-{i + 1:02d}", name, x["_winner"], y["_winner"], weeks,
                    (f"Venc. {x['id']}", f"Venc. {y['id']}")))
            rounds.append(cur)
            prev = cur

        final = rounds[-1][0]
        champion = final["_winner"]
        if champion:
            self.eliminated.pop(champion["id"], None)

        return rounds, draw, champion

    # ---- Toilet Bowl ------------------------------------------------------
    def toilet(self, rounds):
        sf_done = all(m["_winner"] for m in rounds[4])
        finalistas = {m["_winner"]["id"] for m in rounds[4] if m["_winner"]}
        estado = self.week_state(TOILET_WEEK)
        out = {"week": TOILET_WEEK, "state": estado, "ready": sf_done, "series": {}}
        for s in SERIES:
            linhas = []
            for t in self.teams.values():
                if t["series"] != s:
                    continue
                if t["id"] in self.eliminated and t["id"] not in finalistas:
                    linhas.append({"id": t["id"], "name": t["name"], "label": t["label"],
                                   "pf": self.pts(t, TOILET_WEEK)})
            linhas.sort(key=lambda r: (r["pf"] is None, r["pf"] if r["pf"] is not None else 0))
            out["series"][s] = {"teams": linhas,
                                "loser": linhas[0]["id"] if (sf_done and estado == "done" and linhas) else None}
        return out


def run(cfg, sl, nfl_week, state_dir, out_path, force_freeze=False):
    seeds, frozen = get_seeds(sl, cfg, state_dir, nfl_week, force_freeze)
    cup = Cup(sl, cfg, seeds, nfl_week, state_dir)
    rounds, draw, champion = cup.build()
    toilet = cup.toilet(rounds)

    def clean(m):
        m = {k: v for k, v in m.items() if k != "_winner"}
        return m

    data = {
        "generated_at": now_iso(),
        "season": cfg["season"],
        "title": cfg.get("title", "Copa TwoPlatoon"),
        "nfl_week": nfl_week,
        "seeds_frozen": frozen,
        "teams": cup.teams,
        "eliminated": cup.eliminated,
        "standings": seeds,
        "rounds": [{"key": k, "name": n, "weeks": w, "matches": [clean(m) for m in ms]}
                   for (k, n, w), ms in zip(ROUNDS, rounds)],
        "draw": draw,
        "toilet": toilet,
        "champion": champion["id"] if champion else None,
        "warnings": sorted(set(cup.warnings)),
    }
    save_json(out_path, data)
    return data


def main(argv=None):
    p = argparse.ArgumentParser(description="Copa TwoPlatoon")
    p.add_argument("command", choices=["update", "freeze"])
    p.add_argument("--config", default=str(BASE / "config.json"))
    p.add_argument("--mock", action="store_true", help="usa ligas falsas (para testar)")
    p.add_argument("--mock-week", type=int, default=9, help="semana atual da NFL simulada")
    p.add_argument("--state-dir", default=None)
    p.add_argument("--out", default=str(BASE / "docs" / "data" / "cup.json"))
    args = p.parse_args(argv)

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if args.mock:
        sl = MockSleeper(args.mock_week)
        cfg["leagues"] = {s: s for s in SERIES}
    else:
        faltando = [s for s in SERIES if not str(cfg["leagues"].get(s, "")).strip().isdigit()]
        if faltando:
            sys.exit(f"Preencha o league_id das séries {', '.join(faltando)} em config.json.")
        sl = Sleeper()
    state_dir = Path(args.state_dir) if args.state_dir else BASE / ("state_mock" if args.mock else "state")
    nfl_week = sl.nfl_week()
    data = run(cfg, sl, nfl_week, state_dir, Path(args.out), force_freeze=(args.command == "freeze"))
    jogos = sum(len(r["matches"]) for r in data["rounds"])
    for w in data["warnings"]:
        print("ATENÇÃO:", w)
    print(f"OK — semana NFL {nfl_week}, seeds {'congelados' if data['seeds_frozen'] else 'provisórios'}, "
          f"{jogos} confrontos gravados em {args.out}")


if __name__ == "__main__":
    main()
