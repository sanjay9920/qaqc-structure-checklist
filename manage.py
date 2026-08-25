import argparse
from pathlib import Path

from checklist_app.firebase_client import get_db
from checklist_app.qr import save_qr_file
from checklist_app.services import (
    create_structure,
    create_structures_bulk,
    ensure_default_checklist_items,
    format_structure_id,
)


def cmd_seed_checklist(args):
    db = get_db()
    items = ensure_default_checklist_items(db, "cli")
    print(f"Checklist ready with {len(items)} active items.")


def cmd_create_structure(args):
    db = get_db()
    structure = create_structure(
        db, args.structure_id, "cli", project=args.project, block=args.block
    )
    print(f"Created or verified {structure['structure_id']}: {structure['qr_url']}")


def cmd_create_bulk(args):
    db = get_db()
    structures = create_structures_bulk(
        db, args.start, args.end, "cli", project=args.project, block=args.block
    )
    print(f"Created or verified {len(structures)} structures.")
    for structure in structures:
        print(f"{structure['structure_id']} {structure['qr_url']}")


def cmd_qr(args):
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    structure_ids = args.ids or [
        format_structure_id(
            number, args.prefix, args.width, project=args.project, block=args.block
        )
        for number in range(args.start, args.end + 1)
    ]

    for structure_id in structure_ids:
        path = save_qr_file(structure_id, output_dir)
        print(path)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Admin CLI for the Structure QR Checklist system."
    )
    subparsers = parser.add_subparsers(required=True)

    seed = subparsers.add_parser("seed-checklist", help="Create default checklist items.")
    seed.set_defaults(func=cmd_seed_checklist)

    create = subparsers.add_parser("create-structure", help="Create one structure.")
    create.add_argument("structure_id", help="Example: STR-0001")
    create.add_argument("--project", default="", help="Optional project, example: 100MW AKOLA STE")
    create.add_argument("--block", default="", help="Optional block, example: BLOCK-1")
    create.set_defaults(func=cmd_create_structure)

    bulk = subparsers.add_parser("create-bulk", help="Create structures in a number range.")
    bulk.add_argument("--start", type=int, required=True)
    bulk.add_argument("--end", type=int, required=True)
    bulk.add_argument("--project", default="", help="Optional project, example: 100MW AKOLA STE")
    bulk.add_argument("--block", default="", help="Optional block, example: BLOCK-1")
    bulk.set_defaults(func=cmd_create_bulk)

    qr = subparsers.add_parser("qr", help="Generate QR PNG files.")
    qr.add_argument("--ids", nargs="*", help="Specific structure IDs.")
    qr.add_argument("--start", type=int, default=1, help="Start number for range mode.")
    qr.add_argument("--end", type=int, default=1, help="End number for range mode.")
    qr.add_argument("--prefix", default="STR", help="Structure ID prefix.")
    qr.add_argument("--width", type=int, default=4, help="Number padding width.")
    qr.add_argument("--project", default="", help="Optional project, example: 100MW AKOLA STE")
    qr.add_argument("--block", default="", help="Optional block, example: BLOCK-1")
    qr.add_argument("--output", default="generated_qr_codes", help="Output folder.")
    qr.set_defaults(func=cmd_qr)

    return parser


if __name__ == "__main__":
    cli = build_parser()
    parsed_args = cli.parse_args()
    parsed_args.func(parsed_args)
