import argparse
import sys

from sqlalchemy import select

from . import collector, exporter, importer
from .db import get_session, init_db
from .models import MLListing, ProductWatch, Supplier, SupplierProduct


def cmd_init_db(_args: argparse.Namespace) -> None:
    init_db()
    print("Banco de dados inicializado.")


def cmd_collect(args: argparse.Namespace) -> None:
    init_db()
    with get_session() as session:
        listings = collector.collect_by_query(
            session,
            query=args.query,
            max_results=args.limit,
            with_details=not args.no_details,
        )
    print(f"{len(listings)} anuncios coletados/atualizados para o termo '{args.query}'.")


def cmd_import_csv(args: argparse.Namespace) -> None:
    init_db()
    with get_session() as session:
        result = importer.import_csv(session, args.file, source=args.source)
    print(f"Importados: {result['imported']} | Ignorados (sem ID de anuncio): {result['skipped']}")


def cmd_export_excel(args: argparse.Namespace) -> None:
    init_db()
    with get_session() as session:
        exporter.export_to_excel(session, args.output)
    print(f"Planilha exportada para {args.output}")


def cmd_add_supplier(args: argparse.Namespace) -> None:
    init_db()
    with get_session() as session:
        supplier = Supplier(name=args.name, contact=args.contact, notes=args.notes)
        session.add(supplier)
        session.flush()
        print(f"Fornecedor criado com id={supplier.id}: {supplier.name}")


def cmd_add_supplier_product(args: argparse.Namespace) -> None:
    init_db()
    with get_session() as session:
        supplier = session.get(Supplier, args.supplier_id)
        if supplier is None:
            print(f"Fornecedor id={args.supplier_id} nao encontrado.", file=sys.stderr)
            sys.exit(1)
        product = SupplierProduct(
            supplier_id=supplier.id,
            name=args.name,
            sku=args.sku,
            cost_price=args.cost_price,
            moq=args.moq,
            shipping_cost=args.shipping_cost,
            url=args.url,
        )
        session.add(product)
        session.flush()
        print(f"Produto criado com id={product.id}: {product.name}")


def cmd_link_product(args: argparse.Namespace) -> None:
    init_db()
    with get_session() as session:
        supplier_product = session.get(SupplierProduct, args.supplier_product_id)
        if supplier_product is None:
            print(f"Produto de fornecedor id={args.supplier_product_id} nao encontrado.", file=sys.stderr)
            sys.exit(1)

        listing = session.scalar(select(MLListing).where(MLListing.ml_item_id == args.ml_item_id))
        if listing is None:
            print(
                f"Anuncio {args.ml_item_id} nao encontrado no banco. "
                "Rode 'collect' ou 'import-csv' antes de vincular.",
                file=sys.stderr,
            )
            sys.exit(1)

        watch = ProductWatch(
            supplier_product_id=supplier_product.id,
            ml_listing_id=listing.id,
            notes=args.notes,
        )
        session.add(watch)
        print(f"Vinculado: '{supplier_product.name}' <-> anuncio {listing.ml_item_id}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ecommerce_analyzer",
        description="Captura e organiza dados de anuncios do Mercado Livre para escolher produtos.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Cria as tabelas no banco de dados.").set_defaults(func=cmd_init_db)

    p_collect = sub.add_parser("collect", help="Busca anuncios na API do ML e grava um snapshot de preco.")
    p_collect.add_argument("--query", required=True, help="Termo de busca (ex: 'fone bluetooth')")
    p_collect.add_argument("--limit", type=int, default=50, help="Numero maximo de anuncios (padrao: 50)")
    p_collect.add_argument(
        "--no-details", action="store_true", help="Pula a busca de detalhe (sold_quantity) por item, mais rapido"
    )
    p_collect.set_defaults(func=cmd_collect)

    p_import = sub.add_parser("import-csv", help="Importa CSV exportado de ferramenta paga (ex: Avante Pro).")
    p_import.add_argument("--file", required=True, help="Caminho do arquivo CSV")
    p_import.add_argument("--source", required=True, help="Nome da fonte (ex: avante_pro)")
    p_import.set_defaults(func=cmd_import_csv)

    p_export = sub.add_parser("export-excel", help="Exporta os dados do banco para uma planilha Excel.")
    p_export.add_argument("--output", default="relatorio.xlsx", help="Caminho do arquivo de saida")
    p_export.set_defaults(func=cmd_export_excel)

    p_supplier = sub.add_parser("add-supplier", help="Cadastra um fornecedor.")
    p_supplier.add_argument("--name", required=True)
    p_supplier.add_argument("--contact")
    p_supplier.add_argument("--notes")
    p_supplier.set_defaults(func=cmd_add_supplier)

    p_sp = sub.add_parser("add-supplier-product", help="Cadastra um produto candidato de um fornecedor.")
    p_sp.add_argument("--supplier-id", type=int, required=True)
    p_sp.add_argument("--name", required=True)
    p_sp.add_argument("--sku")
    p_sp.add_argument("--cost-price", type=float)
    p_sp.add_argument("--moq", type=int)
    p_sp.add_argument("--shipping-cost", type=float)
    p_sp.add_argument("--url")
    p_sp.set_defaults(func=cmd_add_supplier_product)

    p_link = sub.add_parser("link-product", help="Vincula um produto do fornecedor a um anuncio concorrente no ML.")
    p_link.add_argument("--supplier-product-id", type=int, required=True)
    p_link.add_argument("--ml-item-id", required=True, help="Ex: MLB123456789")
    p_link.add_argument("--notes")
    p_link.set_defaults(func=cmd_link_product)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
