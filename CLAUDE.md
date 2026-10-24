# ECommerce - garimpo de produtos para marketplaces

Ferramenta em Python (CLI) que cruza a tabela de fornecedores com anuncios
concorrentes do Mercado Livre, Shopee e TikTok Shop, estima demanda e lucro
por produto e gera um dashboard HTML com os produtos mais promissores.

## Politica de modelos e agentes (economia de tokens)

- A sessao principal deve DELEGAR para os agentes em `.claude/agents/` em vez
  de rodar os comandos ela mesma. Cada agente declara seu modelo:
  - **haiku**: `coletor-ml`, `extrator-navegador`, `importador-dados`,
    `cadastro-fornecedor`, `relatorio` (so executam comandos da CLI).
  - **sonnet**: `analista-viabilidade` (interpreta o ranking), `orquestrador`
    (roda o ciclo completo).
  - **opus**: `dev-manutencao` (unico que edita codigo).
- Para uso diario, rode a sessao principal em Sonnet (`/model sonnet`).
  Fable/Opus so para mudancas de arquitetura ou depuracao dificil.
- Agentes NAO leem `src/` - usam esta pagina e `--help`. So `dev-manutencao` le codigo.
- Respostas dos agentes: curtas, numeros em tabela, sem repetir o pedido.

## Comandos da CLI (`PYTHONPATH=src python -m ecommerce_analyzer.cli ...`)

| Comando | O que faz |
|---|---|
| `init-db` | cria/migra tabelas (SQLite em `data/ecommerce.db`) |
| `import-suppliers --file tabela.xlsx` | importa fornecedores e produtos (custo, frete, MOQ, termos de busca) |
| `collect --query "termo" --limit 50` | busca anuncios no ML (API oficial, exige token no `.env`) |
| `collect-best-sellers --category MLBxxxx` | top mais vendidos da categoria (API ML) |
| `trends [--category MLBxxxx]` | termos em alta no ML |
| `research --all` / `--product-id N` | coleta pelos termos de cada produto do fornecedor e vincula |
| `scrape --marketplace ml\|shopee\|tiktok --query "termo"` | extrator via navegador logado (so na maquina do usuario) |
| `import-csv --file x.csv --source avante_pro` | importa export de ferramenta paga |
| `match-products` | vincula produtos do fornecedor a anuncios ja coletados |
| `link-product` / `unlink-product` | vinculo manual |
| `score [--top 20] [--marketplace ml] [--json]` | ranking de viabilidade |
| `dashboard --output dashboard.html` | pagina HTML com ranking, filtros e graficos |
| `export-excel --output x.xlsx` | planilha com todas as abas |
| `status` | contagens do banco |
| `seed-demo` | dados ficticios para testar o dashboard |

## Mapa do codigo (para `dev-manutencao`)

- `config.py` variaveis de ambiente | `models.py` tabelas | `db.py` sessao + migracao leve
- `ml_api.py` cliente API ML com OAuth | `collector.py` grava anuncios/snapshots
- `scraper.py` Playwright (ML/Shopee/TikTok), SELECTORS centralizados
- `suppliers_import.py` importa planilha | `matcher.py` vinculo automatico
- `fees.py` taxas por marketplace (override em `data/taxas.json`) | `scoring.py` indicadores e score
- `dashboard.py` gera HTML | `exporter.py` Excel | `cli.py` comandos
- `tests/` pytest | `docs/estudo_viabilidade_extrator.md` estudo e formulas

## Convencoes

- Codigo e comentarios em portugues, sem acentos nos identificadores.
- Nunca inventar dados de coleta; erro de rede/token e reportado literalmente.
- Taxas e impostos sao parametros, nao constantes "magicas" no meio do codigo.
