#!/usr/bin/env python3
"""Schema audit, or explicitly selected isolated no-inference startup observation.

Reads only generated protocol schema, not config, histories, credentials or project
files. --native-startup creates one new App Server in a synthetic temporary cwd,
initializes it and lists loaded thread identifiers twice. It never starts/resumes a
thread or model turn. Closes only its own spawned process. No private payload is printed.
Security must review this mode before the parent explicitly authorizes execution.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile


DEFAULT_SCHEMA = '/private/tmp/dashboard-recovery-schema-20261019'
MAX_SCHEMA_BYTES = 2 * 1024 * 1024


def load_schema(root, name):
    path = root / 'v2' / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SCHEMA_BYTES:
        raise ValueError('invalid_schema')
    schema = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(schema, dict) or not isinstance(schema.get('properties'), dict):
        raise ValueError('invalid_schema')
    return schema


def preflight(root):
    start = load_schema(root, 'ThreadStartParams.json')['properties']
    turn = load_schema(root, 'TurnStartParams.json')['properties']
    response = load_schema(root, 'ThreadStartResponse.json')['properties']
    # Fixed known field names only; do not copy descriptions/native values to output.
    return {
        'status': 'blocked_unverified_assessment_isolation',
        'mode': 'schema_only_no_native_execution',
        'native_started': False,
        'inference_started': False,
        'thread_start_config_supported': 'config' in start,
        'thread_start_dynamic_tools_supported': 'dynamicTools' in start,
        'thread_start_permissions_supported': 'permissions' in start,
        'turn_start_permissions_supported': 'permissions' in turn,
        'response_profile_supported': 'activePermissionProfile' in response,
        'native_tool_free_proven': False,
        'same_thread_resume_proven': False,
        'mandatory_security_controls_preserved': True,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema-dir', type=Path, default=Path(DEFAULT_SCHEMA))
    parser.add_argument('--native-startup', action='store_true')
    args = parser.parse_args(argv)
    if args.native_startup:
        return native_startup()
    try:
        result = preflight(args.schema_dir)
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({'status': 'schema_preflight_unavailable', 'native_started': False,
                          'inference_started': False}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    # A valid schema is a successful preflight, never a successful native capability test.
    return 0


def native_startup():
    # Imports project source, not private runtime/config/history. CLI authentication
    # remains the native CLI's existing boundary; this script reads no credentials.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from dashboard.codex_client import CodexClient, ProtocolError
    from dashboard.recovery_capabilities import RecoveryCapabilities
    import hashlib
    import subprocess
    import uuid

    client = None
    try:
        with tempfile.TemporaryDirectory(prefix='recovery-startup-probe-', dir='/private/tmp') as directory:
            def spawn(argv, **kwargs):
                if argv != ['codex', 'app-server']:
                    raise ValueError('Unsupported startup probe command')
                return subprocess.Popen(argv, cwd=directory, **kwargs)

            client = CodexClient(lambda message: None, lambda: None, process_factory=spawn)
            generation = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
            capabilities = RecoveryCapabilities()
            verified = capabilities.connect_and_observe_startup(client, generation)
            print(json.dumps({'status': 'startup_empty_observed' if verified else 'startup_unverified',
                              'mode': 'isolated_native_no_inference', 'model_turn_requested': False,
                              'old_thread_resumed': False, 'startup_loaded_empty': verified,
                              'reason_codes': list(capabilities.startup_reason_codes)}, sort_keys=True))
            return 0 if verified else 1
    except (OSError, ValueError, ProtocolError):
        print(json.dumps({'status': 'startup_probe_unavailable', 'mode': 'isolated_native_no_inference',
                          'model_turn_requested': False, 'old_thread_resumed': False}, sort_keys=True))
        return 2
    finally:
        if client is not None:
            client.close()


if __name__ == '__main__':
    sys.exit(main())
