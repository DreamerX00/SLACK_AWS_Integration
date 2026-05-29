"""Bridge between the Slack bot and the existing AWS pricing logic."""

import pandas as pd
from main import get_aws_clients, build_ec2_rows, build_rds_rows, write_excel_report

REQUIRED_EC2_COLS = {"instance_type", "region", "os"}
REQUIRED_RDS_COLS = {"instance_type", "region", "engine"}


def generate_cost_report(input_path: str, output_path: str) -> str:
    sheets = pd.read_excel(input_path, sheet_name=None)

    ec2_tuples = []
    rds_tuples = []

    if "EC2" in sheets:
        df = sheets["EC2"]
        lower_cols = {c.lower() for c in df.columns}
        if not REQUIRED_EC2_COLS.issubset(lower_cols):
            raise ValueError(
                f"EC2 sheet must contain columns: {', '.join(sorted(REQUIRED_EC2_COLS))}. "
                f"Got: {', '.join(sorted(lower_cols))}"
            )
        df_renamed = df.rename(columns=str.lower)
        for _, row in df_renamed.iterrows():
            it, reg, osv = row.get("instance_type"), row.get("region"), row.get("os")
            if pd.isna(it) or pd.isna(reg) or pd.isna(osv):
                continue
            ec2_tuples.append((str(it).strip(), str(reg).strip(), str(osv).strip()))

    if "RDS" in sheets:
        df = sheets["RDS"]
        lower_cols = {c.lower() for c in df.columns}
        if not REQUIRED_RDS_COLS.issubset(lower_cols):
            raise ValueError(
                f"RDS sheet must contain columns: {', '.join(sorted(REQUIRED_RDS_COLS))}. "
                f"Got: {', '.join(sorted(lower_cols))}"
            )
        df_renamed = df.rename(columns=str.lower)
        for _, row in df_renamed.iterrows():
            it, reg, eng = row.get("instance_type"), row.get("region"), row.get("engine")
            if pd.isna(it) or pd.isna(reg) or pd.isna(eng):
                continue
            rds_tuples.append((str(it).strip(), str(reg).strip(), str(eng).strip()))

    if not ec2_tuples and not rds_tuples:
        raise ValueError(
            "Input file must contain an 'EC2' sheet, an 'RDS' sheet, or both."
        )

    pricing_client, sp_client = get_aws_clients()

    ec2_rows = build_ec2_rows(pricing_client, sp_client, ec2_tuples) if ec2_tuples else []
    rds_rows = build_rds_rows(pricing_client, rds_tuples) if rds_tuples else []

    if not ec2_rows and not rds_rows:
        raise RuntimeError("No pricing data could be fetched. Check AWS credentials and inputs.")

    return write_excel_report(ec2_rows, rds_rows, output_path)
