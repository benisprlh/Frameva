"""Frozen helper entry; all CLI/MCP modes use the same packaged implementation."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from frameva.cli import main
    raise SystemExit(main())
