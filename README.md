# ECommerce: garimpo de produtos para marketplaces

Cruza a sua tabela de fornecedores com anúncios concorrentes do **Mercado
Livre, Shopee e TikTok Shop**, estima quanto cada produto vende e quanto
sobra de lucro depois das taxas, e gera uma página com os produtos mais
promissores.

Estudo completo (o que dá para extrair, como Avante Pro e Mercado Turbo
funcionam, riscos, fórmulas e taxas): [`docs/estudo_viabilidade_extrator.md`](docs/estudo_viabilidade_extrator.md).

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium        # so para o extrator via navegador
cp .env.example .env               # preencha ML_CLIENT_ID e ML_CLIENT_SECRET
export PYTHONPATH=src              # Windows: set PYTHONPATH=src
```

## Ver funcionando em 1 minuto (dados fictícios)

```bash
python -m ecommerce_analyzer.cli --db sqlite:///data/demo.db seed-demo
python -m ecommerce_analyzer.cli --db sqlite:///data/demo.db dashboard --output dashboard_demo.html
```

Abra `dashboard_demo.html` no navegador.

## Fluxo real

```bash
# 1. Sua tabela de fornecedores (xlsx ou csv). Reconhece colunas como
#    Fornecedor, Produto, SKU, Custo, Frete, MOQ, Palavras-chave, Imposto.
python -m ecommerce_analyzer.cli import-suppliers --file minha_tabela.xlsx

# 2a. Concorrentes no Mercado Livre pela API oficial (precisa do token no .env)
python -m ecommerce_analyzer.cli ml-auth            # uma vez, segue as instrucoes
python -m ecommerce_analyzer.cli research --all     # busca pelos termos de cada produto e vincula

# 2b. Shopee / TikTok Shop / ML pelo navegador logado (na sua maquina)
python -m ecommerce_analyzer.cli scrape --marketplace shopee --login        # uma vez: faca login
python -m ecommerce_analyzer.cli scrape --marketplace shopee --all-products
python -m ecommerce_analyzer.cli scrape --marketplace tiktok --all-products

# 2c. (opcional) CSV exportado da Avante Pro ou similar
python -m ecommerce_analyzer.cli import-csv --file export.csv --source avante_pro

# 3. Vinculos automaticos que faltarem + ranking + pagina
python -m ecommerce_analyzer.cli match-products
python -m ecommerce_analyzer.cli score --top 20 --details
python -m ecommerce_analyzer.cli dashboard --output dashboard.html
```

Rode o passo 2 uma vez por dia. Cada coleta guarda uma foto (snapshot) de
cada anúncio, e a diferença de vendidos entre as fotos é o que dá a
estimativa de vendas por dia mais confiável.

## O que o dashboard mostra

- Produtos viáveis, margem média e o melhor lucro mensal esperado.
- Gráfico de lucro por unidade contra demanda do mercado, por marketplace.
- Top 10 por lucro mensal esperado.
- Ranking com score de 0 a 100, lucro por unidade, margem, preço sugerido,
  unidades por mês no mercado, número de vendedores e alertas. Clicar numa
  linha abre a conta completa (comissão, taxa fixa, imposto, custo), o preço
  de equilíbrio e os anúncios concorrentes usados.

Opções: `--strategy p25` simula vender mais barato que 75% dos concorrentes,
`--ml-plan premium` usa a comissão do anúncio Premium, `--shopee-plan cpf`
para vendedor pessoa física.

## Agentes (economia de tokens)

O projeto tem agentes em `.claude/agents/`, cada um com o modelo mais barato
que dá conta da tarefa. Veja `CLAUDE.md` para a política completa.

| Agente | Modelo | Quando usar |
|---|---|---|
| `importador-dados` | Haiku | importar tabela de fornecedores ou CSV de ferramenta paga |
| `coletor-ml` | Haiku | coletar no ML pela API |
| `extrator-navegador` | Haiku | coletar Shopee/TikTok/ML pelo navegador |
| `cadastro-fornecedor` | Haiku | cadastro avulso e ajuste de vínculos |
| `relatorio` | Haiku | status do banco e Excel |
| `analista-viabilidade` | Sonnet | ranking, dashboard e "o que vale a pena vender" |
| `orquestrador` | Sonnet | rodar o ciclo inteiro |
| `dev-manutencao` | Opus | único que altera código (ex: site mudou o layout) |

## Estrutura

```
src/ecommerce_analyzer/
  config.py            variaveis de ambiente
  models.py / db.py    tabelas e migracao leve
  ml_api.py            API do ML com OAuth
  collector.py         grava anuncios e snapshots
  scraper.py           extrator via navegador (ML, Shopee, TikTok)
  suppliers_import.py  importa a tabela de fornecedores
  importer.py          importa CSV de ferramenta paga
  matcher.py           vinculo automatico produto <-> anuncio
  fees.py              taxas por marketplace
  scoring.py           lucro, demanda, concorrencia, score
  dashboard.py         pagina HTML
  exporter.py          Excel
  demo.py              dados ficticios
  cli.py               comandos
tests/                 python -m pytest -q
samples/               exemplos de planilha de fornecedores e de CSV
```
