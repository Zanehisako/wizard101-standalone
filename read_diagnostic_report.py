#!/usr/bin/env python3
"""Summarize build 15 and build 16 diagnostic reports; absent facts are unavailable."""
import argparse
import json
from pathlib import Path
import zipfile


UNAVAILABLE = 'unavailable'
MAX_REPORT_BYTES = 16 * 1024 * 1024


def load_report(path):
    path = Path(path)
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as archive:
            reports = [info for info in archive.infolist() if info.filename == 'Wizard101 Diagnostics/Diagnostic-Report.json']
            if len(reports) != 1 or reports[0].file_size > MAX_REPORT_BYTES:
                raise ValueError('Expected one diagnostic JSON report of at most 16 MiB in the ZIP')
            return json.loads(archive.read(reports[0]))
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError('Diagnostic report is too large')
    return json.loads(path.read_text())


def summarize(report):
    if not isinstance(report, dict) or report.get('schema') not in (1, 2, 3):
        raise ValueError('Expected a diagnostic report with schema 1, 2 or 3')
    patch = report.get('patch') or {}
    failure = patch.get('latestFailure') or {}
    transfer = failure.get('transfer') or {}
    verification = report.get('archive_verification') or {}
    archives = verification.get('archives') or []
    return {
        'report_schema': report['schema'],
        'app_build': report.get('app_build', UNAVAILABLE),
        'created_utc': report.get('created_utc', UNAVAILABLE),
        'launch_content_mode': report.get('launch_content_mode', UNAVAILABLE),
        'last_launch': report.get('last_launch', UNAVAILABLE),
        'content_readiness': report.get('content_readiness', UNAVAILABLE),
        'primary_preload_failure': {
            'archive': (failure.get('archive') or {}).get('path', UNAVAILABLE),
            'revision': failure.get('revision', UNAVAILABLE),
            'observed_utc': failure.get('observedUTC', UNAVAILABLE),
            'preparation': failure.get('preparation', UNAVAILABLE),
            'phase': failure.get('phase', UNAVAILABLE),
            'verification': failure.get('verification', UNAVAILABLE),
            'requested_range': transfer.get('requestedRange', UNAVAILABLE),
            'received_bytes': transfer.get('receivedBytes', UNAVAILABLE),
            'http_status': transfer.get('httpStatus', UNAVAILABLE),
            'network_code': transfer.get('networkCode', UNAVAILABLE),
            'network_outcome': transfer.get('outcome', UNAVAILABLE),
        },
        'transfer_observations': patch.get('transfers', UNAVAILABLE),
        'archive_manifest_revision': verification.get('revision', UNAVAILABLE),
        'archive_manifest_checked_utc': verification.get('manifest_checked_utc', UNAVAILABLE),
        'archive_statuses': [{
            'archive': item.get('archive', UNAVAILABLE),
            'installed': (item.get('installed') or {}).get('status', UNAVAILABLE),
            'staged': (item.get('staged') or {}).get('status', UNAVAILABLE),
        } for item in archives],
        'log_token_counts': report.get('log_token_counts', UNAVAILABLE),
        'graphics_live_verified': report.get('graphics_live_verified', UNAVAILABLE),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(load_report(args.report)), indent=2))
