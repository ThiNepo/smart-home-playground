"""Application entry point."""
from smarthouse.application import SmartHouseApplication


if __name__ == "__main__":
    raise SystemExit(SmartHouseApplication.run_from_cli())
