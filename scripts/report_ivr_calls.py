#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Genera un reporte diario del IVR a partir del JSONL estructurado "
            "y permite exportar las llamadas deduplicadas."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Ruta del JSONL de eventos. Por defecto intenta usar la configuracion del repo.",
    )
    parser.add_argument(
        "--date",
        type=_parse_date_arg,
        help="Filtra un solo dia en formato YYYY-MM-DD. Si no se indica filtro, usa hoy.",
    )
    parser.add_argument(
        "--from",
        dest="date_from",
        type=_parse_date_arg,
        help="Fecha inicial inclusiva en formato YYYY-MM-DD.",
    )
    parser.add_argument(
        "--to",
        dest="date_to",
        type=_parse_date_arg,
        help="Fecha final inclusiva en formato YYYY-MM-DD.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="No aplica filtro de fecha.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        help="Exporta las llamadas deduplicadas y filtradas a CSV.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        type=Path,
        help="Exporta el reporte estructurado a JSON.",
    )
    args = parser.parse_args(argv)

    if args.all and (
        args.date is not None or args.date_from is not None or args.date_to is not None
    ):
        parser.error("--all no se puede combinar con --date, --from o --to.")

    if args.date is not None and (args.date_from is not None or args.date_to is not None):
        parser.error("--date no se puede combinar con --from o --to.")

    if args.date_from is not None and args.date_to is not None and args.date_from > args.date_to:
        parser.error("--from no puede ser mayor que --to.")

    if not args.all and args.date is None and args.date_from is None and args.date_to is None:
        args.date = date.today()

    return args


def main(argv: list[str] | None = None) -> int:
    from vicidial_vosk_cobranza_ivr.reporting import (
        build_report_payload,
        deduplicate_final_call_events,
        export_events_csv,
        filter_events_by_date,
        load_final_call_events,
        summarize_by_intent,
        summarize_by_state,
        write_report_json,
    )

    args = parse_args(argv)

    try:
        input_path = args.input or resolve_default_input_path()
        all_events = load_final_call_events(input_path)
        deduplicated_events = deduplicate_final_call_events(all_events)
        filtered_events = filter_events_by_date(
            deduplicated_events,
            target_date=args.date,
            date_from=args.date_from,
            date_to=args.date_to,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    by_intent = summarize_by_intent(filtered_events)
    by_state = summarize_by_state(filtered_events)

    print(f"input: {input_path}")
    print(
        "filter:"
        f" date={args.date.isoformat() if args.date is not None else '-'}"
        f" from={args.date_from.isoformat() if args.date_from is not None else '-'}"
        f" to={args.date_to.isoformat() if args.date_to is not None else '-'}"
        f" all={args.all}"
    )
    print(f"events_read: {len(all_events)}")
    print(f"calls_after_dedup: {len(deduplicated_events)}")
    print(f"calls_in_report: {len(filtered_events)}")
    print("summary_by_intent:")
    if by_intent:
        for intent_name, total in by_intent.items():
            print(f"  {intent_name}: {total}")
    else:
        print("  (sin llamadas)")

    print("summary_by_state:")
    if by_state:
        for state_name, total in by_state.items():
            print(f"  {state_name}: {total}")
    else:
        print("  (sin llamadas)")

    if args.csv is not None:
        export_events_csv(filtered_events, args.csv)
        print(f"csv: {args.csv}")

    if args.json_output is not None:
        payload = build_report_payload(
            source_path=input_path,
            events=filtered_events,
            target_date=args.date,
            date_from=args.date_from,
            date_to=args.date_to,
            include_all_dates=args.all,
        )
        write_report_json(payload, args.json_output)
        print(f"json: {args.json_output}")

    return 0


def resolve_default_input_path() -> Path:
    from vicidial_vosk_cobranza_ivr.config import (
        DEFAULT_EVENTS_PATH,
        load_app_config,
        resolve_runtime_paths,
    )

    runtime_paths = resolve_runtime_paths()
    try:
        config = load_app_config(
            runtime_paths.config_path,
            runtime_paths.intents_path,
            runtime_paths.logging_path,
        )
    except Exception:
        return Path(DEFAULT_EVENTS_PATH).expanduser()

    configured_path = config.logging.events_path.strip()
    if not configured_path:
        raise RuntimeError("logging.events_path esta vacio. Usa --input para indicar el JSONL.")

    return Path(configured_path).expanduser()


def _parse_date_arg(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Fecha invalida '{value}'. Usa YYYY-MM-DD.") from exc


if __name__ == "__main__":
    raise SystemExit(main())
