"""
Command-line interface for SQLPilot.
Features Rich syntax highlighting, query result rendering, self-healing telemetry,
and firewall guardrail violation alerts.
"""

import argparse
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .engine import SQLPilotEngine
from .models import SQLPilotResponse
from .providers import MockSQLProvider

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.syntax import Syntax
    from rich.text import Text
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False
    console = None


def render_response(resp: SQLPilotResponse):
    """Render SQLPilot response to console."""
    if HAS_RICH and console:
        console.print()

        # 1. Firewall Violation Alert
        if resp.is_blocked_by_guardrail:
            console.print(Panel(
                f"[bold red]🚫 {resp.guardrail_reason}[/bold red]\n\n"
                f"[dim]Attempted SQL:[/dim]\n{resp.final_sql}",
                title="[bold red]🛡️ SQL Safety Firewall Alert (Blocked)[/bold red]",
                subtitle=f"Latency: {resp.total_latency_ms}ms",
                border_style="red"
            ))
            console.print()
            return

        # 2. Self-Healing Telemetry (if repairs took place)
        if resp.repairs:
            for rep in resp.repairs:
                console.print(Panel(
                    f"[bold yellow]Attempt #{rep.attempt_number} Failed:[/bold yellow] [dim]{rep.error_message}[/dim]\n"
                    f"[bold green]Fix Applied:[/bold green] [bold white]{rep.fix_explanation}[/bold white]\n\n"
                    f"[yellow]Failed SQL:[/yellow] {rep.failed_sql}\n"
                    f"[green]Repaired SQL:[/green] {rep.repaired_sql}",
                    title="[bold yellow]🛠️ Self-Healing Query Repair Triggered[/bold yellow]",
                    border_style="yellow"
                ))
                console.print()

        # 3. Executed SQL
        syntax = Syntax(resp.final_sql, "sql", theme="monokai", line_numbers=False)
        console.print(Panel(
            syntax,
            title="[bold cyan]⚡ Executed SQL Query[/bold cyan]",
            subtitle=f"Latency: {resp.total_latency_ms}ms",
            border_style="cyan"
        ))
        console.print()

        # 4. Result Table
        if resp.result and resp.result.rows:
            table = Table(title=f"📊 Query Results ({resp.result.row_count} rows)", show_header=True, header_style="bold magenta")
            for col in resp.result.columns:
                table.add_column(str(col), style="white")

            for row in resp.result.rows[:15]:
                table.add_row(*[str(val) for val in row])

            if len(resp.result.rows) > 15:
                table.caption = f"Showing 15 of {len(resp.result.rows)} rows"

            console.print(table)
            console.print()

        # 5. Business Summary
        console.print(Panel(
            Text(resp.business_summary, style="bold white"),
            title="[bold green]💡 Executive Business Summary[/bold green]",
            border_style="green"
        ))

        # 6. Assumptions
        if resp.assumptions_made:
            assumptions_txt = " • ".join(resp.assumptions_made)
            console.print(f"[dim yellow]Assumptions:[/dim yellow] [dim]{assumptions_txt}[/dim]\n")
        console.print()

    else:
        print("=" * 70)
        print(f"QUESTION: {resp.user_query}")
        print(f"SQL: {resp.final_sql}")
        if resp.is_blocked_by_guardrail:
            print(f"BLOCKED: {resp.guardrail_reason}")
            return
        if resp.result:
            print(f"RESULTS ({resp.result.row_count} rows):")
            print(" | ".join(resp.result.columns))
            for r in resp.result.rows[:10]:
                print(" | ".join(str(v) for v in r))
        print(f"\nSUMMARY: {resp.business_summary}")
        print(f"LATENCY: {resp.total_latency_ms}ms")
        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="SQLPilot: Autonomous Text-to-SQL engine with self-healing repairs and guardrails."
    )
    parser.add_argument("-q", "--query", type=str, help="Plain English business question to ask")
    parser.add_argument("--db", type=str, default=None, help="Path to SQLite database file")
    parser.add_argument("--mock", action="store_true", help="Run with deterministic offline mock provider")

    args = parser.parse_args()

    provider = MockSQLProvider() if args.mock else None
    engine = SQLPilotEngine(provider=provider)

    # Introspect schema for header banner
    meta = engine.db.introspect_schema()
    table_names = [t.table_name for t in meta.tables]

    if HAS_RICH and console:
        console.print(Panel(
            f"[bold white]Connected Database:[/bold white] [cyan]{engine.db.db_path.name}[/cyan]\n"
            f"[bold white]Available Tables:[/bold white] [green]{', '.join(table_names)}[/green]\n"
            f"[bold white]Safety Policy:[/bold white] [bold green]Strict Read-Only (Non-destructive SELECT only)[/bold green]",
            title="[bold green]🧭 SQLPilot Online[/bold green]",
            border_style="green"
        ))

    if args.query:
        resp = engine.run(args.query)
        render_response(resp)
    else:
        # Interactive shell
        if HAS_RICH and console:
            console.print("[dim]Ask a business question in plain English. Type 'exit' to quit.[/dim]\n")

        while True:
            try:
                user_q = input("SQLPilot > ").strip()
                if not user_q:
                    continue
                if user_q.lower() in ("exit", "quit", "q"):
                    break
                resp = engine.run(user_q)
                render_response(resp)
            except (KeyboardInterrupt, EOFError):
                print()
                break


if __name__ == "__main__":
    main()
