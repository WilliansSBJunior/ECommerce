# ECommerce — Captura de dados para escolha de produtos (Mercado Livre)

Ferramenta para captar dados de anúncios concorrentes no Mercado Livre e cruzar
com o preço de fornecedores, gerando uma base histórica (banco de dados) e uma
planilha Excel para análise manual. Os cálculos de viabilidade/margem ficam de
fora por enquanto — o foco aqui é captura, normalização e armazenamento.

## Como os dados fluem

1. **Fornecedores e produtos candidatos** — você cadastra manualmente (custo,
   frete, MOQ).
2. **Anúncios concorrentes** — vêm de duas fontes:
   - **API pública do Mercado Livre** (`collect`): título, preço, vendidos,
     frete grátis, etc. Sem necessidade de login/token.
   - **Import de CSV** (`import-csv`): dados exportados de ferramentas pagas
     (tipo Avante Pro), que têm métricas mais refinadas. Qualquer coluna que
     não seja reconhecida automaticamente é guardada sem perda em um campo
     extra (`extra_data`), então nenhuma métrica que sua ferramenta paga
     forneça é descartada.
3. Cada coleta gera um **snapshot** (linha de histórico) — o preço de um
   anúncio ao longo do tempo fica registrado, não é sobrescrito.
4. Você **vincula** (`link-product`) um produto do fornecedor aos anúncios
   concorrentes equivalentes, para comparar lado a lado.
5. **Exporta para Excel** (`export-excel`) quando quiser revisar/filtrar.

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Por padrão o banco é SQLite local (`data/ecommerce.db`), sem configuração
nenhuma. Para usar Postgres depois, basta trocar `DATABASE_URL` no `.env`.

## Uso (CLI)

```bash
# Cria as tabelas
python -m ecommerce_analyzer.cli init-db

# Busca anúncios do ML por um termo e grava preço/vendidos como snapshot
python -m ecommerce_analyzer.cli collect --query "fone bluetooth" --limit 50

# Importa dados exportados de uma ferramenta paga
python -m ecommerce_analyzer.cli import-csv --file samples/exemplo_import.csv --source avante_pro

# Cadastra um fornecedor e um produto candidato
python -m ecommerce_analyzer.cli add-supplier --name "Fornecedor A"
python -m ecommerce_analyzer.cli add-supplier-product --supplier-id 1 --name "Fone XYZ" --cost-price 25.90 --shipping-cost 3.50

# Vincula o produto do fornecedor a um anúncio concorrente já coletado
python -m ecommerce_analyzer.cli link-product --supplier-product-id 1 --ml-item-id MLB1234567890

# Exporta tudo para planilha
python -m ecommerce_analyzer.cli export-excel --output relatorio.xlsx
```

Rode `collect` ou `import-csv` periodicamente (sob demanda) para o mesmo
termo/anúncios — cada execução adiciona um novo snapshot, construindo o
histórico de preços que alimenta as métricas futuras.

## Estrutura

```
src/ecommerce_analyzer/
  config.py      # variáveis de ambiente (banco, site do ML)
  models.py      # schema: fornecedores, produtos, anúncios, snapshots, vínculos
  db.py          # engine/sessão do banco
  ml_api.py      # cliente da API pública do Mercado Livre
  collector.py   # grava resultados da API como anúncios + snapshots
  importer.py    # importa CSV de ferramentas pagas (formato flexível)
  exporter.py    # exporta o banco para Excel (múltiplas abas)
  cli.py         # comandos de linha de comando
samples/
  exemplo_import.csv  # modelo de CSV para import-csv
```

## Próximos passos (fora do escopo atual)

- Cálculos de viabilidade (margem, giro, saturação de concorrência etc.) —
  a estrutura de dados já está pronta para receber essas métricas quando
  você trouxer as fórmulas.
- Agendamento automático da coleta (hoje é sob demanda).
