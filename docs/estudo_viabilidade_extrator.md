# Estudo de viabilidade: extrator de dados de marketplaces

Data: 24/10/2026. Objetivo: avaliar se dá para construir um extrator próprio
que entregue os indicadores que ferramentas como Avante Pro e Mercado Turbo
mostram, e para Mercado Livre, Shopee e TikTok Shop.

## Resumo

| Marketplace | Fonte usada pelo projeto | Viável? | Dados que dá para obter |
|---|---|---|---|
| Mercado Livre | API oficial com token (`collect`, `research`, `collect-best-sellers`) | Sim, recomendado | busca, preço, posição, tipo de anúncio, logística (FULL), loja oficial, data de criação, mais vendidos por categoria, tendências de busca |
| Mercado Livre | Extrator no navegador logado (`scrape --marketplace ml`) | Sim, complemento | tudo acima + faixa de vendidos ("+5mil vendidos"), avaliações, patrocinado |
| Shopee | Extrator no navegador logado (`scrape --marketplace shopee`) | Sim, com cuidado | preço, vendidos total e **vendas dos últimos 30 dias**, avaliações, loja |
| TikTok Shop | Extrator no navegador logado (`scrape --marketplace tiktok`) | Parcial | preço, vendidos, avaliações; formato instável, exige manutenção |
| Qualquer um | Import de CSV exportado de ferramenta paga (`import-csv`) | Sim | o que a ferramenta exportar (vendas 30d, faturamento etc.) |

Conclusão: é viável. O que as ferramentas pagas fazem não é mágica, é a
combinação de três coisas que o projeto agora também faz:

1. ler os dados que a própria página/API já entrega (preço, vendidos, posição);
2. **fotografar o mesmo anúncio várias vezes** e calcular a diferença de
   vendidos entre as fotos (é assim que se chega em "vendas por dia");
3. cruzar com taxas e custos para estimar lucro.

A parte que não dá para replicar no curto prazo é o **histórico acumulado**:
a Avante Pro tem meses de fotos de milhões de anúncios. O projeto começa a
acumular histórico a partir da primeira coleta; rodar a coleta 1x por dia por
2 a 4 semanas já dá uma estimativa de vendas/dia confiável para os seus
produtos.

## O que foi testado neste ambiente

Testes feitos em 24/10/2026, de um servidor em nuvem, sem login:

| Teste | Resultado |
|---|---|
| `api.mercadolibre.com/sites/MLB/search` sem token | HTTP 403 `forbidden` |
| `api.mercadolibre.com/items/{id}` sem token | HTTP 403 `PA_UNAUTHORIZED_RESULT_FROM_POLICIES` |
| `lista.mercadolivre.com.br/...` (curl e Chromium headless) | redireciona para `account-verification` (pede login) |
| `shopee.com.br/api/v4/search/search_items` | HTTP 403 |
| `shopee.com.br/search` no Chromium | página carrega sem produtos (pede login) |
| `tiktok.com/shop/s/...` no Chromium | página carrega sem produtos (pede login) |

Consequências para o código:

- O cliente antigo da API do ML (sem token) **já não funcionava**. Foi
  reescrito com OAuth (`ml_api.py`).
- Desde 2025, `sold_quantity` só volta na API para o dono do anúncio. Por isso
  a estimativa de vendas usa o contador "+X vendidos" lido da página e/ou as
  vendas de 30 dias da Shopee/ferramentas pagas.
- O extrator precisa rodar **na sua máquina, com o seu navegador logado**.
  É exatamente por isso que Avante Pro e similares são extensões de navegador:
  elas leem a página que você já abriu logado.

## Como funcionam Avante Pro e Mercado Turbo

- **Avante Pro**: extensão para Chrome/Edge/Opera/Brave no Windows. Mostra
  vendas, margem, CTR e tendência por produto, compara marketplaces e faz
  previsão de sazonalidade. Cobre ML e Shopee; Amazon "em breve". Planos de
  R$ 49,90/mês (1 marketplace) a R$ 99,90/mês (3 marketplaces). Fonte: site
  oficial (avantpro.com.br).
- **Mercado Turbo**: foco maior em gestão da própria conta (anúncios,
  mensagens, financeiro), com acompanhamento de concorrentes, ranking de
  anúncios na busca e palavras-chave mais buscadas na categoria.
- Indicadores típicos dessas ferramentas: vendas estimadas (dia/mês),
  faturamento estimado, idade do anúncio, posição na busca, número de
  vendedores no catálogo, histórico de preço, tipo de anúncio e logística.

Todos esses indicadores estão no projeto, com as fontes da tabela acima.

## Riscos e cuidados

- **Termos de uso**: Mercado Livre, Shopee e TikTok restringem coleta
  automatizada. Use o extrator em volume baixo (dezenas de buscas por dia),
  com o seu login, como uma pessoa navegando. A API oficial do ML é sempre a
  primeira opção.
- **Bloqueio de conta**: uso agressivo pode gerar captcha ou bloqueio da conta
  de comprador usada no navegador. Não use a conta de vendedor principal no
  perfil do extrator.
- **Manutenção**: os sites mudam o HTML e o formato do JSON. Os seletores
  estão centralizados em `scraper.py` (`SELECTORS`) e o extrator salva o HTML/
  JSON bruto em `data/raw/` para corrigir offline. TikTok é o mais instável.
- **Estimativas**: "+5mil vendidos" é o limite inferior da faixa. Vendas/dia
  só ficam boas com histórico (2+ coletas com dias de intervalo).

## Token da API do ML (passo a passo)

1. Entre em https://developers.mercadolivre.com.br/devcenter com sua conta
   e crie um aplicativo. Em "URI de redirect" coloque
   `https://localhost/callback` (ou outra que você controle).
2. Copie `Client ID` e `Client Secret` para o `.env`:
   `ML_CLIENT_ID=...` e `ML_CLIENT_SECRET=...`.
3. Rode `python -m ecommerce_analyzer.cli ml-auth`, abra o link, autorize, e
   copie o `code=` da URL de retorno (a página vai dar erro, é normal).
4. Rode `python -m ecommerce_analyzer.cli ml-auth --code <CODE>` e coloque o
   `ML_REFRESH_TOKEN` exibido no `.env`. Daí em diante o token renova sozinho.
5. Teste com `python -m ecommerce_analyzer.cli ml-auth --test`.

Se o app não tiver permissão para algum recurso (erro
`PA_UNAUTHORIZED_RESULT_FROM_POLICIES`), habilite as permissões funcionais
de leitura nas configurações do app no DevCenter.

## Score: fórmulas

Para cada produto do fornecedor em cada marketplace, usando os anúncios
concorrentes vinculados:

- **Preço de venda simulado**: mediana dos concorrentes (ou 1º quartil, ou o
  menor, com `--strategy`).
- **Custo por unidade** = custo do produto + frete do fornecedor + embalagem.
- **Lucro por unidade** = preço − comissão − taxa fixa − imposto − custo.
- **Margem** = lucro ÷ preço. **Preço de equilíbrio**: menor preço com lucro zero.
- **Vendas/dia de cada anúncio**, em ordem de preferência: diferença de
  vendidos entre a 1ª e a última coleta ÷ dias; vendas de 30 dias ÷ 30;
  vendidos total ÷ idade do anúncio.
- **Mercado/mês** = soma das vendas/dia × 30.
- **Sua fatia** = 1 ÷ (vendedores + 1), no máximo 20%.
  **Lucro mensal esperado** = mercado/mês × sua fatia × lucro por unidade.
- **Score (0 a 100)** = 35% margem (40% de margem = nota cheia) + 30% demanda
  (escala log, 3.000 un/mês = nota cheia) + 20% concorrência (até 5
  vendedores = nota cheia, 60+ = zero; −30% se um vendedor tem mais de 60%
  das vendas) + 15% lucro por unidade (R$ 50 = nota cheia). Produto com
  margem negativa fica com score máximo de 25.

Pesos e limites estão no topo de `scoring.py`.

## Taxas usadas (referência out/2026, confira na central do vendedor)

| Marketplace | Regra |
|---|---|
| ML Clássico | ~13% (11–14% por categoria) + custo fixo R$ 6,25–6,75 abaixo de R$ 79 (não cobrado em FULL/Agência/Coleta) |
| ML Premium | ~18% (15–19%) + mesmo custo fixo |
| Shopee CNPJ | até R$ 79,99: 20% + R$ 4,50; R$ 80–99,99: 14% + R$ 16; R$ 100–199,99: 14% + R$ 20; R$ 200+: 14% + R$ 26 (CPF: +R$ 3) |
| TikTok Shop | abaixo de R$ 50: 10% + R$ 4; R$ 50+: 6% + R$ 6; programa de frete 6% (teto R$ 50) |

Para ajustar sem mexer no código, crie `data/taxas.json` (exemplo em
`fees.py`). Imposto padrão 6% (`DEFAULT_TAX_RATE` no `.env` ou coluna
"imposto" na planilha).

## Garimpo reverso (mais vendidos -> fornecedor)

Fluxo: `categories` (descobre ids) -> `reverse` (grava os mais vendidos da
categoria com fonte `mais_vendidos_ml`/`mais_vendidos_shopee` e
`extra_data {"categoria", "rank"}`, e procura cada um no fornecedor) ->
`opportunities` / `dashboard` (status encontrado/não encontrado, custo no
fornecedor e lucro por unidade vendendo no preço do anúncio).

| Etapa | Fonte | Situação |
|---|---|---|
| Categorias ML | API `/sites/MLB/categories` e `/categories/{id}` | estável, exige token |
| Categorias Shopee | `shopee.com.br/api/v4/pages/get_category_tree` no navegador logado | **não validado ao vivo**; parser procura qualquer lista com `catid` |
| Mais vendidos ML | API `/highlights/MLB/category/{id}` | exige token |
| Mais vendidos ML (sem token) | página `mercadolivre.com.br/mais-vendidos/{categoria}` | **não validado ao vivo**; reaproveita o parser de cards `poly-card`; id pode ser de catálogo (`/p/MLB...`) |
| Mais vendidos Shopee | `shopee.com.br/x-cat.{catid}?sortBy=sales` (JSON interceptado) | **não validado ao vivo** |
| Busca no fornecedor | `search_url` com `{q}` + seletores / JSON-LD / heurística de preço R$ | heurística; sites diferentes podem exigir `--selectors` |

Casamento: similaridade do `matcher` (fração das palavras do termo presentes
no título, com penalidade quando o código de modelo difere) entre o produto
do catálogo e o título do anúncio. Na busca do site, o termo é o título sem
palavras de marketing (`query_from_title`) e o resultado aceito é o de maior
similaridade acima do limite. Revise os vínculos antes de comprar: título
parecido não garante que é o mesmo produto (cor, voltagem, kit).

## Fontes

- [Avante Pro, site oficial](https://avantpro.com.br/)
- [Mercado Turbo no GetApp](https://www.getapp.com/all-software/a/mercado-turbo)
- [Mercado Livre, permissões funcionais (erro PolicyAgent)](https://developers.mercadolivre.com.br/pt-br/permissoes-funcionais)
- [Mercado Livre, publicação de produtos (sold_quantity só com token do dono)](https://developers.mercadolivre.com.br/pt-br/publicacao-de-produtos)
- [Relato de 403 em chamadas sem token desde 2025](https://anythingmcp.com/ru/guides/connect-mercado-libre-to-claude)
- [Comissões de marketplace 2026](https://www.ruacep.com.br/guias/ecommerce/comissao-marketplace-ml-amazon-shopee-magalu-2026/)
- [Custo fixo do ML 2026](https://jaguarsheet.com/pt/blog/costo-fijo-mercado-livre)
- [Comissões ML por categoria](https://yav.com.br/comissoes-marketplace/)
- [Calculadora Shopee](https://priceva.com/pt/calculadora-shopee)
- [Mudanças na Shopee em 2026](https://actana.com.br/blog/mudancas-na-shopee-em-2026)
- [Taxas do TikTok Shop 2026](https://www.viniensina.com.br/taxas-tiktok-shop/)
- [TikTok Shop, taxas antes da Black Friday](https://economicnewsbrasil.com.br/2026/09/30/taxas-tiktok-shop-black-friday-lojistas/)
