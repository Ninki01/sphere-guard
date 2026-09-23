"""
Entry point for the SphereGuard Firebase uploader.

Usage (run from the robots/ directory):
    python -m shared.uploader --config sg01/config.yaml

Credentials are read from environment variables only (set via systemd EnvironmentFile
/etc/sphereguard/uploader.env — never from the repository):

    SG_FIREBASE_KEY    /etc/sphereguard/firebase-key.json
    SG_STORAGE_BUCKET  sphere-guard-2025.firebasestorage.app
"""

import argparse
import os
import sys
from pathlib import Path

from shared.config.loader        import load_config
from shared.uploader.uploader    import run, print_status
from shared.util.log             import info, warn, error as log_error

_ENV_KEY    = "SG_FIREBASE_KEY"
_ENV_BUCKET = "SG_STORAGE_BUCKET"
_ENV_FILE   = "/etc/sphereguard/uploader.env"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SphereGuard FIFO Firebase uploader"
    )
    parser.add_argument("--config",  required=True, help="Path to config.yaml (from robots/)")
    parser.add_argument("--once",    action="store_true",
                        help="Process one pass then exit (testing)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be uploaded, touch nothing")
    parser.add_argument("--status",  action="store_true",
                        help="Print queue status and exit")
    args = parser.parse_args()

    cfg      = load_config(args.config)
    data_dir = cfg.paths.data_dir
    robot_id = cfg.robot.id

    # Emit the resolved absolute path so path-resolution issues are immediately
    # visible in journalctl, rather than silently reporting an empty queue.
    info(f"[UPLOADER] robot={robot_id}  data_dir={data_dir}")
    if not Path(data_dir).exists():
        warn(
            f"[UPLOADER] data_dir does not exist: {data_dir}\n"
            f"  (resolved from paths.data_dir in {cfg.paths._config_path})\n"
            f"  Queue will be empty until the directory is created or the path is corrected."
        )

    if args.status:
        print_status(Path(data_dir))
        sys.exit(0)

    key_path = os.environ.get(_ENV_KEY, "").strip()
    bucket   = os.environ.get(_ENV_BUCKET, "").strip()

    if not args.dry_run:
        if not key_path:
            log_error(
                f"[UPLOADER] {_ENV_KEY} is not set.\n"
                f"  Create {_ENV_FILE} with:\n"
                f"    {_ENV_KEY}=/etc/sphereguard/firebase-key.json\n"
                f"    {_ENV_BUCKET}=<your-project>.firebasestorage.app\n"
                f"  Then: sudo systemctl daemon-reload && sudo systemctl restart uploader"
            )
            sys.exit(1)
        if not Path(key_path).exists():
            log_error(
                f"[UPLOADER] Firebase key not found: {key_path}\n"
                f"  Place the service account JSON at that path:\n"
                f"    sudo cp firebase-key.json {key_path}\n"
                f"    sudo chmod 600 {key_path}\n"
                f"  The key MUST NOT be inside the repository directory."
            )
            sys.exit(1)
        if not bucket:
            log_error(
                f"[UPLOADER] {_ENV_BUCKET} is not set in {_ENV_FILE}."
            )
            sys.exit(1)

    run(
        data_dir = data_dir,
        robot_id = robot_id,
        key_path = key_path,
        bucket   = bucket,
        once     = args.once,
        dry_run  = args.dry_run,
    )


if __name__ == "__main__":
    main()
