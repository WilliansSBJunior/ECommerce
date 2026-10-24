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

## Garimpo reverso (dos mais vendidos para o fornecedor)

O fluxo acima parte da tabela do fornecedor. O garimpo reverso faz o
contrário: descobre os **mais vendidos de uma categoria** no Mercado Livre ou
na Shopee e verifica se o fornecedor que você indicar tem esses produtos.

```bash
# 1. Descobrir categorias
python -m ecommerce_analyzer.cli categories --marketplace ml                       # API (token)
python -m ecommerce_analyzer.cli categories --marketplace ml --parent MLB1000      # subcategorias
python -m ecommerce_analyzer.cli categories --marketplace shopee                   # navegador logado

# 2. (opcional) Site do fornecedor: busca com {q} no lugar do termo
python -m ecommerce_analyzer.cli supplier-site --supplier-id 1 --search-url "https://site.com/busca?q={q}"
python -m ecommerce_analyzer.cli supplier-login --supplier-id 1                    # se o preco so aparece logado
python -m ecommerce_analyzer.cli supplier-site --supplier-id 1 --test "fone bluetooth"   # confere a leitura
#    se vier vazio/errado, informe seletores CSS:
#    --selectors '{"item": "div.produto", "title": "a.nome", "price": ".preco", "link": "a.nome"}'

# 3. Mais vendidos -> grava -> procura no catalogo importado e no site do fornecedor
python -m ecommerce_analyzer.cli reverse --marketplace ml --category MLB1000 --supplier-id 1
python -m ecommerce_analyzer.cli reverse --marketplace ml --category MLB1000 --source scrape    # sem token
python -m ecommerce_analyzer.cli reverse --marketplace shopee --category 11059983 --supplier-id 1
python -m ecommerce_analyzer.cli reverse --marketplace shopee --url "https://shopee.com.br/...-cat.11059983?sortBy=sales"

# 4. Lista de oportunidades (status, custo no fornecedor, lucro/un) e pagina
python -m ecommerce_analyzer.cli opportunities --only-missing
python -m ecommerce_analyzer.cli opportunities --csv mais_vendidos.csv
python -m ecommerce_analyzer.cli dashboard --output dashboard.html   # inclui a secao "Mais vendidos por categoria"
```

Como casa: primeiro procura no catálogo já importado (`import-suppliers`)
pela similaridade entre os termos do produto e o título do anúncio
(`--threshold`, padrão 0,6). Se não achar e o fornecedor tiver `search_url`,
busca no site dele com os termos do título (sem palavras de marketing),
escolhe o resultado mais parecido e cria o produto do fornecedor com o preço
do site. Sem `--supplier-id`, procura só no catálogo de todos os fornecedores.
O lucro por unidade simula vender no preço do anúncio mais vendido (taxa do
marketplace, imposto padrão, custo, frete e embalagem).

Limitações: o endpoint de categorias da Shopee, a página pública de mais
vendidos do ML e a página de categoria da Shopee não puderam ser validados ao
vivo (os sites bloqueiam o servidor de desenvolvimento); a leitura do site do
fornecedor é heurística e pode exigir seletores. Os brutos ficam em `data/raw/`.

## O que o dashboard mostra

- Produtos viáveis, margem média e o melhor lucro mensal esperado.
- Gráfico de lucro por unidade contra demanda do mercado, por marketplace.
- Top 10 por lucro mensal esperado.
- Ranking com score de 0 a 100, lucro por unidade, margem, preço sugerido,
  unidades por mês no mercado, número de vendedores e alertas. Clicar numa
  linha abre a conta completa (comissão, taxa fixa, imposto, custo), o preço
  de equilíbrio e os anúncios concorrentes usados.
- Mais vendidos por categoria (quando houver garimpo reverso): rank, canal,
  categoria, preço, vendidos, vendas/dia, se o fornecedor tem (✔/✖), custo
  no fornecedor e lucro por unidade, com filtro Encontrados/Não encontrados.

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
| `garimpo-reverso` | Haiku | mais vendidos por categoria e se o fornecedor tem |
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
  discovery.py         garimpo reverso: mais vendidos, casamento, oportunidades
  supplier_search.py   busca no site do fornecedor (seletores, JSON-LD, heuristica)
  fees.py              taxas por marketplace
  scoring.py           lucro, demanda, concorrencia, score
  dashboard.py         pagina HTML
  exporter.py          Excel
  demo.py              dados ficticios
  cli.py               comandos
tests/                 python -m pytest -q
samples/               exemplos de planilha de fornecedores e de CSV
```
