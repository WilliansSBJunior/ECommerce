import argparse
import json
import sys
from datetime import date

from sqlalchemy import func, select

from . import collector, db, exporter, importer
from .models import (
    MARKETPLACE_LABELS,
    MARKETPLACES,
    MLListing,
    MLListingSnapshot,
    ProductWatch,
    Supplier,
    SupplierProduct,
)


def _session():
    db.init_db()
    return db.get_session()


def _fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(1)


def _ml_call(fn, *a, **kw):
    """Roda uma chamada da API do ML e transforma erro de token em mensagem clara."""
    from .ml_api import MLAuthError

    try:
        return fn(*a, **kw)
    except MLAuthError as exc:
        _fail(f"ERRO API ML: {exc}")


# ---------------------------------------------------------------- banco/status
def cmd_init_db(_args) -> None:
    db.init_db()
    print("Banco de dados inicializado.")


def cmd_status(_args) -> None:
    with _session() as s:
        print(f"Fornecedores: {s.scalar(select(func.count(Supplier.id)))}")
        print(f"Produtos de fornecedor: {s.scalar(select(func.count(SupplierProduct.id)))}")
        linked = s.scalar(select(func.count(func.distinct(ProductWatch.supplier_product_id))))
        print(f"Produtos com concorrentes vinculados: {linked}")
        print(f"Vinculos produto <-> anuncio: {s.scalar(select(func.count(ProductWatch.id)))}")
        for mk in MARKETPLACES:
            n = s.scalar(select(func.count(MLListing.id)).where(MLListing.marketplace == mk))
            print(f"Anuncios {MARKETPLACE_LABELS[mk]}: {n}")
        rows = s.execute(select(MLListingSnapshot.source, func.count(), func.max(MLListingSnapshot.captured_at)).group_by(MLListingSnapshot.source)).all()
        for source, n, last in rows:
            print(f"Snapshots fonte '{source}': {n} (ultimo: {last:%d/%m/%Y %H:%M})")


# ---------------------------------------------------------------- API do ML
def cmd_ml_auth(args) -> None:
    from . import ml_api

    if args.code:
        data = _ml_call(ml_api.exchange_code, args.code)
        print("Token salvo em data/ml_token.json. Para renovar sozinho, coloque no .env:")
        print(f"ML_REFRESH_TOKEN={data.get('refresh_token')}")
        return
    if args.test:
        token = _ml_call(ml_api.get_access_token)
        res = _ml_call(ml_api.search_items, "fone bluetooth", max_results=1)
        print(f"OK: token valido ({token[:10]}...), busca retornou {len(res)} item.")
        return
    print("1. Abra no navegador e autorize o app:")
    print("   " + ml_api.authorization_url())
    print("2. Copie o parametro ?code=... da URL para onde foi redirecionado e rode:")
    print("   python -m ecommerce_analyzer.cli ml-auth --code <CODE>")


def cmd_collect(args) -> None:
    with _session() as s:
        listings = _ml_call(
            collector.collect_by_query, s, query=args.query, max_results=args.limit,
            with_details=not args.no_details, supplier_product_id=args.product_id, category=args.category,
        )
    print(f"{len(listings)} anuncios coletados/atualizados para o termo '{args.query}'.")


def cmd_collect_best_sellers(args) -> None:
    with _session() as s:
        listings = _ml_call(collector.collect_best_sellers, s, args.category)
    print(f"{len(listings)} mais vendidos gravados da categoria {args.category}.")
    for l in listings[: args.show]:
        print(f"  {l.ml_item_id}  {l.title[:70]}")


def cmd_trends(args) -> None:
    from . import ml_api

    trends = _ml_call(ml_api.get_trends, args.category)
    for i, t in enumerate(trends[: args.limit], 1):
        print(f"{i:>3}. {t.get('keyword')}")


def cmd_research(args) -> None:
    """Para cada produto do fornecedor, busca no ML pelos termos dele e vincula
    os anuncios cujo titulo bate com o produto (matcher)."""
    from .matcher import match_product

    with _session() as s:
        q = select(SupplierProduct)
        if args.product_id:
            q = q.where(SupplierProduct.id == args.product_id)
        elif not args.all:
            _fail("Informe --all ou --product-id N")
        products = s.scalars(q).all()
        for p in products:
            found = []
            for term in p.query_terms():
                found += _ml_call(collector.collect_by_query, s, term, max_results=args.limit, with_details=not args.no_details)
            linked = match_product(s, p, threshold=args.threshold, candidates=found)
            print(f"[{p.id}] {p.name}: {len(found)} anuncios, {len(linked)} vinculados")


# ---------------------------------------------------------------- extrator
def cmd_scrape(args) -> None:
    from . import scraper
    from .matcher import match_product

    if args.login:
        scraper.login(args.marketplace)
        print("Sessao salva no perfil do navegador. Agora rode o scrape sem --login.")
        return
    jobs: list[tuple[int | None, str]] = []
    with _session() as s:
        if args.all_products or args.product_id:
            q = select(SupplierProduct)
            if args.product_id:
                q = q.where(SupplierProduct.id == args.product_id)
            for p in s.scalars(q).all():
                jobs += [(p.id, t) for t in p.query_terms()]
        if args.query:
            jobs.append((None, args.query))
    if not jobs:
        _fail("Informe --query, --product-id ou --all-products")

    pw, ctx = scraper.open_browser(headless=args.headless)
    try:
        for product_id, term in jobs:
            try:
                products, raw = scraper.scrape_search(
                    args.marketplace, term, limit=args.limit, details=args.details, ctx=ctx
                )
            except scraper.ScrapeBlocked as exc:
                _fail(str(exc))
            with _session() as s:
                n = scraper.store_products(s, products, source=f"scrape_{args.marketplace}")
                linked = 0
                if product_id:
                    p = s.get(SupplierProduct, product_id)
                    ids = [x["id"] for x in products]
                    cands = s.scalars(select(MLListing).where(MLListing.ml_item_id.in_(ids))).all()
                    linked = len(match_product(s, p, threshold=args.threshold, candidates=cands))
            msg = f"{args.marketplace} '{term}': {n} anuncios gravados"
            if product_id:
                msg += f", {linked} vinculados ao produto {product_id}"
            if n == 0:
                msg += f" (0 resultados - confira o bruto em {raw}.*)"
            print(msg)
    finally:
        ctx.close()
        pw.stop()


# ---------------------------------------------------------------- imports
def cmd_import_csv(args) -> None:
    with _session() as s:
        result = importer.import_csv(s, args.file, source=args.source)
    print(f"Importados: {result['imported']} | Ignorados (sem ID de anuncio): {result['skipped']}")
    print("Colunas reconhecidas: " + ", ".join(f"{k}<-{v}" for k, v in result["mapping"].items()))


def cmd_import_suppliers(args) -> None:
    from .suppliers_import import import_suppliers

    manual = dict(m.split("=", 1) for m in (args.map or []))
    with _session() as s:
        try:
            r = import_suppliers(s, args.file, sheet=args.sheet, default_supplier=args.supplier, manual_map=manual)
        except ValueError as exc:
            _fail(str(exc))
    print(f"Produtos criados: {r['created']} | atualizados: {r['updated']} | linhas ignoradas: {r['skipped']} | fornecedores: {r['suppliers']}")
    print("Colunas reconhecidas: " + ", ".join(f"{k}<-{v}" for k, v in r["mapping"].items()))
    for w in r["warnings"][:20]:
        print("AVISO: " + w)


def cmd_add_supplier(args) -> None:
    with _session() as s:
        supplier = Supplier(name=args.name, contact=args.contact, notes=args.notes)
        s.add(supplier)
        s.flush()
        print(f"Fornecedor criado com id={supplier.id}: {supplier.name}")


def cmd_add_supplier_product(args) -> None:
    with _session() as s:
        supplier = s.get(Supplier, args.supplier_id)
        if supplier is None:
            _fail(f"Fornecedor id={args.supplier_id} nao encontrado.")
        product = SupplierProduct(
            supplier_id=supplier.id, name=args.name, sku=args.sku, cost_price=args.cost_price,
            moq=args.moq, shipping_cost=args.shipping_cost, url=args.url, search_terms=args.search_terms,
            packaging_cost=args.packaging_cost, tax_rate=args.tax_rate,
        )
        s.add(product)
        s.flush()
        print(f"Produto criado com id={product.id}: {product.name}")


# ---------------------------------------------------------------- vinculos
def _get_listing(s, external_id):
    listing = s.scalar(select(MLListing).where(MLListing.ml_item_id == external_id))
    if listing is None:
        _fail(f"Anuncio {external_id} nao encontrado no banco. Rode 'collect', 'scrape' ou 'import-csv' antes.")
    return listing


def cmd_link_product(args) -> None:
    with _session() as s:
        sp = s.get(SupplierProduct, args.supplier_product_id)
        if sp is None:
            _fail(f"Produto de fornecedor id={args.supplier_product_id} nao encontrado.")
        listing = _get_listing(s, args.ml_item_id)
        created = collector.link(s, sp.id, listing)
        if args.notes:
            w = s.scalar(select(ProductWatch).where(ProductWatch.supplier_product_id == sp.id, ProductWatch.ml_listing_id == listing.id))
            w.notes = args.notes
        print(("Vinculado" if created else "Ja estava vinculado") + f": '{sp.name}' <-> anuncio {listing.ml_item_id}")


def cmd_unlink_product(args) -> None:
    with _session() as s:
        listing = _get_listing(s, args.ml_item_id)
        w = s.scalar(select(ProductWatch).where(ProductWatch.supplier_product_id == args.supplier_product_id, ProductWatch.ml_listing_id == listing.id))
        if w is None:
            _fail("Vinculo nao existe.")
        s.delete(w)
        print(f"Desvinculado: produto {args.supplier_product_id} <-> {args.ml_item_id}")


def cmd_match_products(args) -> None:
    from .matcher import match_all

    with _session() as s:
        result = match_all(s, threshold=args.threshold, product_id=args.product_id)
        total = sum(result.values())
        names = {p.id: p.name for p in s.scalars(select(SupplierProduct)).all()}
    print(f"{total} vinculos novos criados.")
    for pid, n in result.items():
        if n:
            print(f"  [{pid}] {names.get(pid)}: +{n}")


# ---------------------------------------------------------------- analise
def _scores(s, args):
    from .scoring import score_all

    plans = {}
    if getattr(args, "ml_plan", None):
        plans["ml"] = args.ml_plan
    if getattr(args, "shopee_plan", None):
        plans["shopee"] = args.shopee_plan
    results = score_all(s, price_strategy=args.strategy, plan_by_marketplace=plans)
    if getattr(args, "marketplace", None):
        results = [r for r in results if r.marketplace == args.marketplace]
    return results


def cmd_score(args) -> None:
    with _session() as s:
        results = _scores(s, args)
    if not results:
        _fail("Nenhum produto com concorrentes vinculados. Rode import-suppliers, research/scrape e match-products antes.")
    top = results[: args.top]
    if args.json:
        print(json.dumps([r.to_dict() for r in top], ensure_ascii=False, default=str, indent=1))
        return
    hdr = f"{'#':>3} {'Score':>5} {'Canal':<7} {'Produto':<38} {'Lucro/un':>9} {'Margem':>7} {'Preco':>8} {'Merc/mes':>8} {'Vend':>4} {'Lucro/mes':>10}"
    print(hdr)
    print("-" * len(hdr))
    for i, r in enumerate(top, 1):
        fmt = lambda v, f: (f.format(v) if v is not None else "-")
        print(
            f"{i:>3} {r.score:>5.1f} {r.marketplace:<7} {r.product_name[:38]:<38} "
            f"{fmt(r.unit_profit, '{:>9.2f}'):>9} {fmt(r.margin and r.margin * 100, '{:>6.1f}%'):>7} "
            f"{fmt(r.suggested_price, '{:>8.2f}'):>8} {fmt(r.market_units_month, '{:>8.0f}'):>8} {r.n_sellers:>4} "
            f"{fmt(r.expected_profit_month, '{:>10.0f}'):>10}"
        )
        if args.details and r.flags:
            print(f"      alertas: {', '.join(r.flags)}")


def cmd_dashboard(args) -> None:
    from .dashboard import render_dashboard

    with _session() as s:
        results = _scores(s, args)
    path = render_dashboard(results, args.output, strategy=args.strategy)
    print(f"Dashboard gerado: {path} ({len(results)} linhas). Abra no navegador.")


def cmd_export_excel(args) -> None:
    with _session() as s:
        exporter.export_to_excel(s, args.output)
    print(f"Planilha exportada para {args.output}")


def cmd_seed_demo(args) -> None:
    from .demo import seed_demo

    with _session() as s:
        if s.scalar(select(func.count(MLListing.id))) and not args.force:
            _fail("O banco ja tem anuncios. Use outro banco (--db sqlite:///data/demo.db) ou --force.")
        r = seed_demo(s, args.file)
    print(f"Demo criada: {r['listings']} anuncios ficticios, {r['snapshots']} snapshots.")


# ---------------------------------------------------------------- parser
def _add_score_opts(p):
    p.add_argument("--strategy", choices=["median", "p25", "min"], default="median",
                   help="Preco de venda simulado: mediana do mercado, 1o quartil ou menor preco")
    p.add_argument("--marketplace", choices=list(MARKETPLACES))
    p.add_argument("--ml-plan", choices=["classico", "premium"], help="Tipo de anuncio no ML (padrao: classico)")
    p.add_argument("--shopee-plan", choices=["padrao", "cpf"], help="Shopee: CNPJ (padrao) ou CPF")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ecommerce_analyzer",
        description="Garimpo de produtos: cruza fornecedores com anuncios do Mercado Livre, Shopee e TikTok Shop.",
    )
    parser.add_argument("--db", help="URL do banco (sobrescreve DATABASE_URL), ex: sqlite:///data/demo.db")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Cria/migra as tabelas.").set_defaults(func=cmd_init_db)
    sub.add_parser("status", help="Contagens do banco.").set_defaults(func=cmd_status)

    p = sub.add_parser("ml-auth", help="Autoriza o app na API do ML (gera refresh token).")
    p.add_argument("--code", help="code recebido no redirect")
    p.add_argument("--test", action="store_true", help="Testa se o token funciona")
    p.set_defaults(func=cmd_ml_auth)

    p = sub.add_parser("collect", help="Busca anuncios na API do ML e grava snapshot.")
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--category", help="Restringe a uma categoria (ex: MLB1055)")
    p.add_argument("--product-id", type=int, help="Ja vincula todos os resultados a este produto")
    p.add_argument("--no-details", action="store_true", help="Pula o detalhe por item (mais rapido)")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("collect-best-sellers", help="Mais vendidos de uma categoria do ML.")
    p.add_argument("--category", required=True)
    p.add_argument("--show", type=int, default=20)
    p.set_defaults(func=cmd_collect_best_sellers)

    p = sub.add_parser("trends", help="Termos mais buscados no ML.")
    p.add_argument("--category")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_trends)

    p = sub.add_parser("research", help="Coleta no ML pelos termos de cada produto do fornecedor e vincula.")
    p.add_argument("--all", action="store_true")
    p.add_argument("--product-id", type=int)
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--threshold", type=float, default=0.6)
    p.add_argument("--no-details", action="store_true")
    p.set_defaults(func=cmd_research)

    p = sub.add_parser("scrape", help="Extrator via navegador logado (ML, Shopee, TikTok Shop).")
    p.add_argument("--marketplace", choices=list(MARKETPLACES), required=True)
    p.add_argument("--query")
    p.add_argument("--product-id", type=int)
    p.add_argument("--all-products", action="store_true")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--threshold", type=float, default=0.6)
    p.add_argument("--details", action="store_true", help="ML: abre cada anuncio para ler vendidos (lento)")
    p.add_argument("--headless", action="store_true", help="Sem janela (mais bloqueado pelos sites)")
    p.add_argument("--login", action="store_true", help="Abre a pagina de login para salvar a sessao")
    p.set_defaults(func=cmd_scrape)

    p = sub.add_parser("import-csv", help="Importa CSV exportado de ferramenta paga (ex: Avante Pro).")
    p.add_argument("--file", required=True)
    p.add_argument("--source", required=True)
    p.set_defaults(func=cmd_import_csv)

    p = sub.add_parser("import-suppliers", help="Importa a tabela de fornecedores (xlsx/csv).")
    p.add_argument("--file", required=True)
    p.add_argument("--sheet", help="Nome da aba (xlsx)")
    p.add_argument("--supplier", help="Nome do fornecedor quando a planilha nao tem essa coluna")
    p.add_argument("--map", action="append", metavar="CAMPO=COLUNA",
                   help="Forca mapeamento, ex: --map cost_price='Preco Atacado'. Campos: supplier, name, sku, "
                        "cost_price, shipping_cost, moq, url, search_terms, weight_grams, packaging_cost, tax_rate, category_hint")
    p.set_defaults(func=cmd_import_suppliers)

    p = sub.add_parser("add-supplier", help="Cadastra um fornecedor.")
    p.add_argument("--name", required=True)
    p.add_argument("--contact")
    p.add_argument("--notes")
    p.set_defaults(func=cmd_add_supplier)

    p = sub.add_parser("add-supplier-product", help="Cadastra um produto candidato de um fornecedor.")
    p.add_argument("--supplier-id", type=int, required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--sku")
    p.add_argument("--cost-price", type=float)
    p.add_argument("--moq", type=int)
    p.add_argument("--shipping-cost", type=float)
    p.add_argument("--packaging-cost", type=float)
    p.add_argument("--tax-rate", type=float, help="0.06 = 6%%")
    p.add_argument("--search-terms", help="Termos de busca separados por ';'")
    p.add_argument("--url")
    p.set_defaults(func=cmd_add_supplier_product)

    p = sub.add_parser("link-product", help="Vincula produto do fornecedor a um anuncio concorrente.")
    p.add_argument("--supplier-product-id", type=int, required=True)
    p.add_argument("--ml-item-id", required=True, help="Id externo: MLB123..., shopee:..., tiktok:...")
    p.add_argument("--notes")
    p.set_defaults(func=cmd_link_product)

    p = sub.add_parser("unlink-product", help="Remove um vinculo.")
    p.add_argument("--supplier-product-id", type=int, required=True)
    p.add_argument("--ml-item-id", required=True)
    p.set_defaults(func=cmd_unlink_product)

    p = sub.add_parser("match-products", help="Vincula automaticamente produtos a anuncios ja coletados.")
    p.add_argument("--product-id", type=int)
    p.add_argument("--threshold", type=float, default=0.6)
    p.set_defaults(func=cmd_match_products)

    p = sub.add_parser("score", help="Ranking de viabilidade.")
    _add_score_opts(p)
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--details", action="store_true", help="Mostra alertas por produto")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("dashboard", help="Gera a pagina HTML com o ranking.")
    _add_score_opts(p)
    p.add_argument("--output", default="dashboard.html")
    p.set_defaults(func=cmd_dashboard)

    p = sub.add_parser("export-excel", help="Exporta o banco para Excel.")
    p.add_argument("--output", default=f"relatorio_{date.today():%Y-%m-%d}.xlsx")
    p.set_defaults(func=cmd_export_excel)

    p = sub.add_parser("seed-demo", help="Popula o banco com dados FICTICIOS para testar.")
    p.add_argument("--file", default="samples/exemplo_fornecedores.csv")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_seed_demo)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.db:
        db.configure(args.db)
    args.func(args)


if __name__ == "__main__":
    main()
