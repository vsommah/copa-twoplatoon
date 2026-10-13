# 🪖 Copa TwoPlatoon

Site estático + script Python que busca as 5 ligas (Séries A–E) na Sleeper,
congela os seeds, faz o sorteio, monta o chaveamento e atualiza os placares sozinho.

```
copa.py                      <- o "cérebro" (só biblioteca padrão do Python 3.9+)
config.json                  <- coloque aqui o ID de cada liga
docs/index.html              <- a landing page (lê docs/data/cup.json)
state/seeds.json             <- seeds congelados (gerado sozinho)
state/draw.json              <- sorteio da Fase 2 (gerado sozinho)
.github/workflows/update.yml <- atualização automática a cada 30 min
tests/test_copa.py           <- testes (python -m unittest discover -s tests)
```

## 1. Hospedagem gratuita: GitHub Pages (recomendado)

É grátis, o endereço fica `https://SEU-USUARIO.github.io/NOME-DO-REPO/` e dá para
atualizar os placares automaticamente com o GitHub Actions (sem servidor).
Alternativas gratuitas parecidas: Cloudflare Pages e Netlify (servem a pasta `docs`),
mas a atualização automática fica mais simples no GitHub.

**Passo a passo**

1. Crie uma conta em github.com e um repositório **público** (ex.: `copa-twoplatoon`).
2. Envie todos estes arquivos para ele (botão *Add file → Upload files*; mantenha as pastas, inclusive `.github`).
3. Em **Settings → Pages**: *Source = Deploy from a branch*, branch `main`, pasta **/docs**.
4. Em **Settings → Actions → General → Workflow permissions**: marque **Read and write permissions**.
5. Edite `config.json` e troque cada `COLE_AQUI...` pelo **league_id** da série
   (é o número grande que aparece no link da liga: `sleeper.com/leagues/`**`123456789012345678`**).
6. Aba **Actions → Atualizar Copa → Run workflow**. Em ~1 min o site está no ar.
   Depois disso ele roda sozinho a cada 30 minutos (se o GitHub pausar o agendamento por
   inatividade, é só reativar na aba Actions).

> O repositório é público, então nomes de time e usuários da Sleeper ficam visíveis para quem tiver o link.

## 2. Rodando no seu computador

```bash
python copa.py update --mock --mock-week 9   # testa com ligas FALSAS
python copa.py update                        # de verdade (precisa dos IDs)
cd docs && python -m http.server 8000        # abra http://localhost:8000
```

## 3. Como as regras foram implementadas

| Etapa | Semanas | O que o código faz |
|---|---|---|
| Seeds | 1–5 | Tabela de cada série por % de vitórias, desempate por PF. **Congela sozinho** na primeira execução depois que a Sleeper passa para a semana 6 (`state/seeds.json`). |
| Fase 1 | 6–7 | 56 times em ordem: A5…A12, B1…B12, C1…C12, D1…D12, E1…E12. O 1º enfrenta o último, o 2º o penúltimo… (mesma lógica da planilha de 2025: B5×D12, C1×D4, C5×C12…). |
| Fase 2 | 8–9 | 28 vencedores + A1–A4. **Sorteio** assim que a Fase 1 acaba, com semente pública `copa-2026-<soma dos PF da Fase 1>` (qualquer um reproduz). A1 e A2 ficam em metades opostas e A3/A4 nos outros dois quartos da chave; cada um enfrenta um vencedor sorteado. Salvo em `state/draw.json`. |
| Oitavas → Semis | 10–15 | Vencedor do jogo 1 × vencedor do jogo 2, 3 × 4, etc. |
| Toilet Bowl | 16 | Todos os eliminados; o menor PF da S16 em cada série leva o 💩. |
| Final | 17 | Jogo único, maior PF. |

Os pontos vêm do `matchups/{semana}` da liga de cada time (o PF dele naquela semana, seja
qual for o adversário na liga).

**Decisões que tomei e você pode mudar**
- **Desempate no agregado**: maior PF nas semanas 1–5 (função `match` em `copa.py`).
- **Sorteio**: é aleatório, mas reproduzível. Para refazer, apague `state/draw.json`.
- **Refazer os seeds**: apague `state/seeds.json`. `python copa.py freeze` congela na hora
  (só use depois de a semana 5 terminar).

## 4. Pontos de atenção

- Os placares das semanas 15–17 dependem de a liga seguir listando os times nos confrontos
  (ligas sem consolation bracket podem omitir quem saiu dos playoffs). Se isso acontecer, o
  site mostra um aviso ⚠️ e o `copa.py` imprime `ATENÇÃO` em vez de falhar em silêncio.
- Placares ficam "ao vivo" na semana corrente e só decidem o confronto quando a semana encerra.
