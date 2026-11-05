import json

from django.core.management.base import BaseCommand

from apps.hunter import funnel


class Command(BaseCommand):
    help = "Weekly sends and human replies per site, plus outreach reply rate."

    def add_arguments(self, parser):
        parser.add_argument("--weeks", type=int, default=8)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        rows = funnel.weekly(options["weeks"])
        reach = funnel.outreach_counts(options["weeks"])
        if options["json"]:
            self.stdout.write(json.dumps({"weeks": rows, "outreach": reach}))
            return
        self.stdout.write(
            f"{'week':<9} {'site':<10} {'sent':>5} {'conf':>5} {'rej':>5} {'human':>6} {'rate':>6}"
        )
        totals = {"sent": 0, "human": 0}
        for row in rows:
            totals["sent"] += row["sent"]
            totals["human"] += row["human"]
            self.stdout.write(
                f"{row['week']:<9} {row['source']:<10} {row['sent']:>5} {row['confirmed']:>5} "
                f"{row['rejected']:>5} {row['human']:>6} {row['rate']:>5}%"
            )
        rate = round(100 * totals["human"] / totals["sent"], 1) if totals["sent"] else 0.0
        self.stdout.write(f"Total: {totals['sent']} sent, {totals['human']} human replies, {rate}%")
        self.stdout.write(
            f"Outreach: {reach['draft']} drafts, {reach['sent']} sent, {reach['replied']} replied, "
            f"{reach['skipped']} skipped; reply rate {reach['reply_rate']}%"
        )
